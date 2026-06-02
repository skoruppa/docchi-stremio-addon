"""Shared cache for anime metadata."""
import asyncio
import time
import orjson
import urllib.parse
from config import Config
from app.utils.anime_mapping import get_ids_from_mal_id, get_all_seasons_for_tvdb_id
from app.db import execute

CACHE_TTL = 2592000  # 1 month
VIDEOS_TTL_AIRING = 43200  # 12 hours for airing series
VIDEOS_TTL_FINISHED = 2592000  # 1 month for finished series
VIDEOS_TTL_UNTRANSLATED = 120  # 2 minutes for fallback (untranslated) content
_mem_cache: dict[str, tuple[dict, float]] = {}  # mal_id -> (meta, timestamp)
_videos_mem_cache: dict[str, tuple[list, float, int]] = {}  # mal_id -> (videos, timestamp, ttl_override)
_translating_in_progress: set[str] = set()  # mal_ids currently being translated (dedup)


async def get_cached_meta(mal_id: str):
    """Get cached metadata by MAL ID."""
    if mal_id in _mem_cache:
        meta, ts = _mem_cache[mal_id]
        if time.time() - ts < CACHE_TTL:
            return meta
        del _mem_cache[mal_id]
    rows = await execute("SELECT meta, timestamp FROM meta_cache WHERE mal_id=?", (mal_id,))
    if rows:
        if time.time() - rows[0]['timestamp'] < CACHE_TTL:
            meta = orjson.loads(rows[0]['meta'])
            return meta
        await execute("DELETE FROM meta_cache WHERE mal_id=?", (mal_id,))
    return None


async def set_cached_meta(mal_id: str, meta: dict):
    """Cache metadata by MAL ID with timestamp (videos excluded)."""
    meta_to_cache = {k: v for k, v in meta.items() if k != 'videos'}
    await execute(
        "INSERT OR REPLACE INTO meta_cache (mal_id, meta, timestamp) VALUES (?,?,?)",
        (mal_id, orjson.dumps(meta_to_cache).decode(), int(time.time()))
    )


async def get_cached_videos(mal_id: str) -> list | None:
    """Get cached videos by MAL ID, respecting TTL based on airing status or override."""
    if mal_id in _videos_mem_cache:
        videos, ts, ttl_override = _videos_mem_cache[mal_id]
        ttl = ttl_override if ttl_override else _videos_ttl(videos)
        if time.time() - ts < ttl:
            return videos
        del _videos_mem_cache[mal_id]

    rows = await execute("SELECT videos, timestamp FROM videos_cache WHERE mal_id=?", (mal_id,))
    if rows:
        videos = orjson.loads(rows[0]['videos'])
        ts = rows[0]['timestamp']
        ttl = _videos_ttl(videos)
        if time.time() - ts < ttl:
            _videos_mem_cache[mal_id] = (videos, ts, 0)
            return videos
        await execute("DELETE FROM videos_cache WHERE mal_id=?", (mal_id,))
    return None


async def set_cached_videos(mal_id: str, videos: list, ttl_override: int = 0):
    """Cache videos list by MAL ID. If ttl_override > 0, use that instead of computed TTL."""
    await execute(
        "INSERT OR REPLACE INTO videos_cache (mal_id, videos, timestamp) VALUES (?,?,?)",
        (mal_id, orjson.dumps(videos).decode(), int(time.time()))
    )
    _videos_mem_cache[mal_id] = (videos, int(time.time()), ttl_override)


def _videos_ttl(videos: list) -> int:
    """Determine TTL for videos cache: 12h if has future episodes, 1 month otherwise."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    for v in videos:
        released = v.get('released')
        if not released:
            # No date = probably still airing
            return VIDEOS_TTL_AIRING
        try:
            ep_date = datetime.fromisoformat(released.replace('Z', '+00:00'))
            if ep_date > now:
                return VIDEOS_TTL_AIRING
        except (ValueError, TypeError):
            continue
    return VIDEOS_TTL_FINISHED


def build_genre_links(meta: dict, is_vip: bool = False, catalog_id: str = 'season'):
    """Build genre links for meta using the correct manifest URL and catalog."""
    from app.routes.manifest import genres as manifest_genres
    manifest_path = f"{Config.VIP_PATH}/manifest.json" if is_vip else "manifest.json"
    transport_url = urllib.parse.quote(f"{Config.PROTOCOL}://{Config.REDIRECT_URL}/{manifest_path}", safe='')
    genres = [g for g in meta.get('genres', []) if g in manifest_genres]
    meta['links'] = meta.get('links', []) + [
        {'name': genre, 'category': 'Genres',
         'url': f"stremio:///discover/{transport_url}/anime/{catalog_id}?genre={genre}"}
        for genre in genres
    ]


def with_genre_links(meta: dict, is_vip: bool) -> dict:
    """Return a copy of meta with genre links added."""
    meta = dict(meta)
    meta['links'] = list(meta.get('links', []))
    build_genre_links(meta, is_vip)
    return meta

async def batch_fetch_and_cache_meta(content_ids: list[str], is_vip: bool = False) -> dict[str, dict | None]:
    """Batch version of fetch_and_cache_meta. Fetches cache in one query, then resolves misses concurrently.

    Args:
        content_ids: List of content IDs in format mal:123
        is_vip: Whether VIP features are enabled

    Returns:
        dict mapping each content_id to its metadata (or None if not found)
    """
    mal_id_map = {}  # mal_id -> content_id
    for cid in content_ids:
        parts = cid.split(':')
        if parts[0] == 'mal' and len(parts) > 1:
            mal_id_map[parts[1]] = cid

    results = {cid: None for cid in content_ids}

    if not mal_id_map:
        return results

    placeholders = ','.join('?' * len(mal_id_map))
    mal_ids = list(mal_id_map.keys())
    rows = await execute(
        f"SELECT mal_id, meta, timestamp FROM meta_cache WHERE mal_id IN ({placeholders})",
        tuple(mal_ids)
    )

    cached_mal_ids = set()
    for row in rows:
        if time.time() - row['timestamp'] < CACHE_TTL:
            meta = orjson.loads(row['meta'])
            cid = mal_id_map[str(row['mal_id'])]
            _mem_cache[str(row['mal_id'])] = (meta, row['timestamp'])
            results[cid] = with_genre_links(meta, is_vip)
            cached_mal_ids.add(str(row['mal_id']))

    missing = [mal_id_map[mid] for mid in mal_ids if mid not in cached_mal_ids]
    if missing:
        fetched = await asyncio.gather(*[fetch_and_cache_meta(cid, is_vip) for cid in missing])
        
        # Collect untranslated descriptions for batch translation
        untranslated_entries = []
        for i, (cid, (meta, mal_id)) in enumerate(zip(missing, fetched)):
            if meta and mal_id:
                _mem_cache[mal_id] = (meta, int(time.time()))
                if meta.get('_untranslated'):
                    meta.pop('_untranslated', None)
                    untranslated_entries.append((mal_id, meta))
            results[cid] = meta

        # Inline batch translation with timeout (don't block too long)
        if untranslated_entries:
            try:
                await asyncio.wait_for(
                    _translate_batch_and_cache(untranslated_entries), timeout=15
                )
            except asyncio.TimeoutError:
                pass

    return results


async def fetch_and_cache_meta(content_id: str, is_vip: bool = False):
    """Fetch metadata from TVDB (primary), Kitsu, or MAL (fallbacks) and cache it.
    
    Args:
        content_id: Content ID in format mal:123, kitsu:456, or tt1234567 (IMDB)
        is_vip: Whether VIP features are enabled (for IMDB support)
    
    Returns:
        tuple: (metadata dict or None, mal_id used for fetching)
    """
    # Parse content_id and convert to MAL ID
    parts = content_id.split(':')
    prefix = parts[0]
    mal_id = None

    if prefix == 'mal' and len(parts) > 1:
        mal_id = parts[1]
    elif prefix.startswith('tt') and is_vip and len(parts) >= 1:
        from app.routes import mapping
        season = int(parts[1]) if len(parts) > 1 else None
        mal_id = mapping.get_mal_id_from_imdb_id(prefix, season)
    elif prefix == 'kitsu' and len(parts) > 1:
        from app.routes import mapping
        mal_id = mapping.get_mal_id_from_kitsu_id(parts[1])
    
    if not mal_id:
        return None, None

    def _with_genre_links(meta):
        meta = dict(meta)
        meta['links'] = list(meta.get('links', []))
        build_genre_links(meta, is_vip)
        return meta

    # Check cache first
    cached = await get_cached_meta(mal_id)
    if cached:
        return _with_genre_links(cached), mal_id

    # Try TVDB API first (primary source)
    if Config.TVDB_API_KEY:
        try:
            from app.api.tvdb import get_anime_meta as tvdb_get_meta
            ids = get_ids_from_mal_id(mal_id)
            if ids.get('tvdb_id') and ids.get('tvdb_season') is not None:
                meta = await tvdb_get_meta(
                    tvdb_id=ids['tvdb_id'],
                    mal_id=mal_id,
                    season_number=int(ids['tvdb_season']),
                    imdb_id=ids.get('imdb_id'),
                    tmdb_id=ids.get('tmdb_id'),
                )
                if meta and meta.get('name'):
                    is_untranslated = meta.pop('_untranslated', False)
                    await _fill_genres_from_docchi(meta, mal_id)
                    if is_untranslated:
                        # Try quick inline translation (10s timeout)
                        import logging
                        from app.utils.translate import translate_to_polish
                        logging.info(f"[Translate] Inline translation for mal:{mal_id}")
                        try:
                            translated = await asyncio.wait_for(
                                translate_to_polish(meta.get('description', '')), timeout=10
                            )
                            if translated:
                                meta['description'] = translated
                                logging.info(f"[Translate] Success for mal:{mal_id}")
                            else:
                                logging.warning(f"[Translate] Got None for mal:{mal_id}")
                        except asyncio.TimeoutError:
                            logging.warning(f"[Translate] Timeout for mal:{mal_id}")
                        await set_cached_meta(mal_id, meta)
                    else:
                        await set_cached_meta(mal_id, meta)
                    return _with_genre_links(meta), mal_id
        except Exception as e:
            import logging
            logging.error(f"[TVDB meta] Exception for mal:{mal_id}: {type(e).__name__}: {e}")
            pass
    try:
        from app.api.kitsu import get_anime_meta as kitsu_get_meta
        ids = get_ids_from_mal_id(mal_id)
        if ids['kitsu_id']:
            meta = await kitsu_get_meta(ids['kitsu_id'], mal_id=mal_id,
                                        imdb_id=ids['imdb_id'], tvdb_id=ids['tvdb_id'], tmdb_id=ids['tmdb_id'])
            if meta and meta.get('name'):
                await _fill_genres_from_docchi(meta, mal_id)
                await set_cached_meta(mal_id, meta)
                return _with_genre_links(meta), mal_id
    except Exception:
        pass

    # Fallback to MAL API if Kitsu fails
    if Config.MAL_CLIENT_ID:
        try:
            from app.api.mal import get_anime_meta as mal_get_meta
            meta = await mal_get_meta(mal_id)
            if meta:
                await _fill_genres_from_docchi(meta, mal_id)
                await set_cached_meta(mal_id, meta)
                return _with_genre_links(meta), mal_id
        except Exception:
            pass

    return None, None


async def _fill_genres_from_docchi(meta: dict, mal_id: str):
    if meta.get('genres'):
        return
    try:
        from app.utils.anime_mapping import get_slug_from_mal_id
        from app.routes import docchi_client
        slug = await get_slug_from_mal_id(mal_id)
        if not slug:
            return
        details = await docchi_client.get_anime_details(slug)
        if details and details.get('genres'):
            meta['genres'] = details['genres']
    except Exception:
        pass


async def _translate_and_cache_meta(mal_id: str, meta: dict):
    """Background task: translate description and update cache."""
    import logging
    if mal_id in _translating_in_progress:
        return
    _translating_in_progress.add(mal_id)
    try:
        from app.utils.translate import translate_to_polish
        desc = meta.get('description', '')
        logging.info(f"[Translate] Starting translation for mal:{mal_id} ({len(desc)} chars)")
        translated = await translate_to_polish(desc)
        if translated:
            meta['description'] = translated
            await set_cached_meta(mal_id, meta)
            _mem_cache[mal_id] = (meta, int(time.time()))
            logging.info(f"[Translate] Success for mal:{mal_id}")
        else:
            logging.warning(f"[Translate] Failed for mal:{mal_id} - got None")
    except Exception as e:
        logging.error(f"[Translate] Exception for mal:{mal_id}: {e}")
    finally:
        _translating_in_progress.discard(mal_id)


async def _translate_batch_and_cache(entries: list[tuple[str, dict]]):
    """Background task: batch translate descriptions and update cache."""
    # Filter out already-in-progress
    entries = [(mid, m) for mid, m in entries if mid not in _translating_in_progress]
    if not entries:
        return
    for mid, _ in entries:
        _translating_in_progress.add(mid)
    try:
        from app.utils.translate import batch_translate_to_polish
        texts = [meta.get('description', '') for _, meta in entries]
        translations = await batch_translate_to_polish(texts)
        for (mal_id, meta), translated in zip(entries, translations):
            if translated:
                meta['description'] = translated
                await set_cached_meta(mal_id, meta)
                _mem_cache[mal_id] = (meta, int(time.time()))
    except Exception:
        pass
    finally:
        for mid, _ in entries:
            _translating_in_progress.discard(mid)


async def _translate_videos_background(mal_id: str, tvdb_id: int, all_seasons: list, airs_time: str, original_country: str):
    """Background task: translate episode overviews and update videos cache."""
    key = f"videos:{mal_id}"
    if key in _translating_in_progress:
        return
    _translating_in_progress.add(key)
    try:
        from app.api.tvdb import _fetch_episodes_for_lang, _build_videos_from_episodes
        from app.utils.translate import batch_translate_to_polish

        # Load previously cached videos to reuse already-translated overviews
        prev_cached = await get_cached_videos(mal_id)
        prev_overview_map = {}  # vid_id -> overview
        if prev_cached:
            for v in prev_cached:
                if v.get("overview") and v.get("id"):
                    prev_overview_map[v["id"]] = v["overview"]

        videos = []
        for season_entry in all_seasons:
            entry_mal_id = str(season_entry.get('mal_id', mal_id))
            tvdb_season = season_entry.get('season', {}).get('tvdb')
            if tvdb_season is None:
                continue

            # Get English episodes for translation source
            eng_episodes = await _fetch_episodes_for_lang(tvdb_id, int(tvdb_season), "eng")
            pol_episodes = await _fetch_episodes_for_lang(tvdb_id, int(tvdb_season), "pol")

            # Merge: use Polish where available, then prev cache, then queue for AI
            pol_map = {ep.get("number"): ep for ep in pol_episodes if ep.get("number")}
            to_translate = []
            ep_refs = []

            for ep in eng_episodes:
                num = ep.get("number", 0)
                if num <= 0:
                    continue
                vid_id = f"mal:{entry_mal_id}:{num}"
                pol_ep = pol_map.get(num, {})
                if pol_ep.get("overview"):
                    ep["overview"] = pol_ep["overview"]
                elif vid_id in prev_overview_map:
                    # Reuse previously translated overview
                    ep["overview"] = prev_overview_map[vid_id]
                elif ep.get("overview"):
                    to_translate.append(ep["overview"])
                    ep_refs.append(ep)
                if pol_ep.get("name"):
                    ep["name"] = pol_ep["name"]

            # Batch translate only genuinely new/missing overviews
            if to_translate:
                translations = await batch_translate_to_polish(to_translate[:30])
                for ep, translated in zip(ep_refs[:30], translations):
                    if translated:
                        ep["overview"] = translated

            season_videos = _build_videos_from_episodes(eng_episodes, entry_mal_id, int(tvdb_season), airs_time, original_country)
            for v in season_videos:
                v['season'] = int(tvdb_season)
            videos.extend(season_videos)

        if videos:
            await _enrich_thumbnails({'videos': videos}, mal_id)
            await set_cached_videos(mal_id, videos)
    except Exception:
        pass
    finally:
        _translating_in_progress.discard(key)


async def fetch_videos(mal_id: str) -> list:
    """Fetch videos/episodes for a given MAL ID with caching.
    
    Cache TTL: 12h for airing series (has future episode dates), 1 month for finished.
    When TVDB is configured, fetches episodes for ALL seasons sharing the same tvdb_id.
    """
    import logging

    # Check cache first
    cached = await get_cached_videos(mal_id)
    if cached is not None:
        return cached

    ids = get_ids_from_mal_id(mal_id)
    videos = []

    # Try TVDB first with multi-season support
    if Config.TVDB_API_KEY and ids.get('tvdb_id') and ids.get('tvdb_season') is not None:
        try:
            from app.api.tvdb import get_series_episodes, _build_videos_from_episodes, get_series_extended
            tvdb_id = ids['tvdb_id']

            # Get airs time and country from series record
            series_ext = await get_series_extended(tvdb_id)
            airs_time = (series_ext or {}).get("airsTime") or "00:00"
            original_country = (series_ext or {}).get("originalCountry") or ""

            # Get all seasons that share the same tvdb_id
            all_seasons = get_all_seasons_for_tvdb_id(tvdb_id)
            logging.info(f"[TVDB] mal_id={mal_id}, tvdb_id={tvdb_id}, all_seasons={all_seasons}")
            if not all_seasons:
                # Fallback: just fetch for the current season
                all_seasons = [{'mal_id': int(mal_id), 'season': {'tvdb': ids['tvdb_season']}}]

            for season_entry in all_seasons:
                entry_mal_id = str(season_entry.get('mal_id', mal_id))
                tvdb_season = season_entry.get('season', {}).get('tvdb')
                if tvdb_season is None:
                    continue

                episodes = await get_series_episodes(tvdb_id, season_number=int(tvdb_season), lang="pol")
                logging.info(f"[TVDB] Season {tvdb_season} (mal:{entry_mal_id}): got {len(episodes)} episodes")
                season_videos = _build_videos_from_episodes(episodes, entry_mal_id, int(tvdb_season), airs_time, original_country)

                # Set the season number to the TVDB season for proper multi-season display
                for v in season_videos:
                    v['season'] = int(tvdb_season)

                videos.extend(season_videos)

            if videos:
                await _enrich_thumbnails({'videos': videos}, mal_id)
                # Check if any episodes have untranslated content
                has_untranslated = any(v.get("_untranslated") for v in videos)
                # Strip internal flags before serving
                for v in videos:
                    v.pop("_untranslated", None)
                
                if has_untranslated:
                    # Try inline translation with timeout
                    try:
                        await asyncio.wait_for(
                            _translate_videos_background(mal_id, tvdb_id, all_seasons, airs_time, original_country),
                            timeout=15
                        )
                        # Reload from cache if translation succeeded
                        translated_videos = await get_cached_videos(mal_id)
                        if translated_videos:
                            return translated_videos
                    except asyncio.TimeoutError:
                        pass
                
                cache_ttl = VIDEOS_TTL_UNTRANSLATED if has_untranslated else 0
                await set_cached_videos(mal_id, videos, ttl_override=cache_ttl)
                return videos
        except Exception as e:
            logging.error(f"[TVDB] fetch_videos error: {e}", exc_info=True)

    # Fallback to Kitsu
    if ids.get('kitsu_id'):
        try:
            from app.api.kitsu import get_anime_meta as kitsu_get_meta
            meta = await kitsu_get_meta(ids['kitsu_id'], mal_id=mal_id,
                                        imdb_id=ids['imdb_id'], tvdb_id=ids['tvdb_id'], tmdb_id=ids['tmdb_id'])
            videos = meta.get('videos', []) if meta else []
        except Exception:
            pass

    if not videos and Config.MAL_CLIENT_ID:
        try:
            from app.api.mal import get_anime_meta as mal_get_meta
            meta = await mal_get_meta(mal_id)
            videos = meta.get('videos', []) if meta else []
        except Exception:
            pass

    await _enrich_thumbnails({'videos': videos}, mal_id)
    if videos:
        await set_cached_videos(mal_id, videos)
    return videos


async def _enrich_thumbnails(meta: dict, mal_id: str):
    """Fill missing episode thumbnails from Docchi API."""
    videos = meta.get('videos', [])
    if not videos or all(v.get('thumbnail') for v in videos):
        return
    try:
        from app.utils.anime_mapping import get_slug_from_mal_id
        from app.routes import docchi_client
        slug = await get_slug_from_mal_id(mal_id)
        if not slug:
            return
        episodes = await docchi_client.get_available_episodes(slug)
        if not isinstance(episodes, list):
            return
        thumb_map = {e['anime_episode_number']: e['bg'] for e in episodes if e.get('bg')}
        for v in videos:
            if not v.get('thumbnail'):
                v['thumbnail'] = thumb_map.get(v.get('episode'))
    except Exception:
        pass
