"""Shared cache for anime metadata."""
import asyncio
import time
import orjson
import urllib.parse
from config import Config
from app.utils.anime_mapping import get_ids_from_mal_id, get_all_seasons_for_tvdb_id
from app.db import execute

CACHE_TTL = 2592000  # 1 month
VIDEOS_TTL_AIRING = 10800  # 3 hours for airing series
VIDEOS_TTL_FINISHED = 2592000  # 1 month for finished series
_mem_cache: dict[str, tuple[dict, float]] = {}  # mal_id -> (meta, timestamp)
_videos_mem_cache: dict[str, tuple[list, float, int]] = {}  # mal_id -> (videos, timestamp, ttl_override)


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


async def _get_expired_meta(mal_id: str) -> dict | None:
    """Get expired cached meta (for reusing old translations). Does not delete."""
    rows = await execute("SELECT meta FROM meta_cache WHERE mal_id=?", (mal_id,))
    if rows:
        return orjson.loads(rows[0]['meta'])
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
    """Determine TTL for videos cache.
    
    - If has future episodes: min(12h, time until next episode premiere)
    - If all episodes aired: 1 month
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    next_premiere = None
    
    for v in videos:
        released = v.get('released')
        if not released:
            # No date = probably still airing, use 12h
            return VIDEOS_TTL_AIRING
        try:
            ep_date = datetime.fromisoformat(released.replace('Z', '+00:00'))
            if ep_date > now:
                if next_premiere is None or ep_date < next_premiere:
                    next_premiere = ep_date
        except (ValueError, TypeError):
            continue
    
    if next_premiere:
        # Cap TTL at time until next episode airs (so available flips to true on time)
        seconds_until = int((next_premiere - now).total_seconds())
        return max(60, min(VIDEOS_TTL_AIRING, seconds_until))
    
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
        
        for i, (cid, (meta, mal_id)) in enumerate(zip(missing, fetched)):
            if meta and mal_id:
                _mem_cache[mal_id] = (meta, int(time.time()))
            results[cid] = meta

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

    # Check for expired cache to reuse translations
    expired_meta = await _get_expired_meta(mal_id)

    # Try TVDB API first (primary source)
    if Config.TVDB_API_KEY:
        try:
            from app.api.tvdb import get_anime_meta as tvdb_get_meta
            ids = get_ids_from_mal_id(mal_id)
            if ids.get('tvdb_id'):
                tvdb_season = int(ids['tvdb_season']) if ids.get('tvdb_season') is not None else 1
                meta = await tvdb_get_meta(
                    tvdb_id=ids['tvdb_id'],
                    mal_id=mal_id,
                    season_number=tvdb_season,
                    imdb_id=ids.get('imdb_id'),
                    tmdb_id=ids.get('tmdb_id'),
                )
                if meta and meta.get('name'):
                    is_untranslated = meta.pop('_untranslated', False)
                    await _fill_genres_from_docchi(meta, mal_id)
                    if is_untranslated:
                        # Mark description as needing translation — cron job will handle it
                        meta['_untranslated_description'] = True
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


async def _get_episode_counts(mal_ids: list[str]) -> list[int]:
    """Get episode count for each MAL ID from Kitsu API.
    
    Returns list of episode counts in same order as input.
    Falls back to 0 if unavailable (will use remaining episodes).
    """
    import aiohttp as _aiohttp
    counts = []
    for mid in mal_ids:
        try:
            from app.utils.anime_mapping import get_kitsu_from_mal_id
            kitsu_id = get_kitsu_from_mal_id(mid)
            if kitsu_id:
                async with _aiohttp.ClientSession(timeout=_aiohttp.ClientTimeout(total=5)) as session:
                    async with session.get(f"https://kitsu.io/api/edge/anime/{kitsu_id}",
                                           headers={"Accept": "application/vnd.api+json", "User-Agent": "Mozilla/5.0"},
                                           params={"fields[anime]": "episodeCount"}) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            ep_count = data.get("data", {}).get("attributes", {}).get("episodeCount") or 0
                            counts.append(int(ep_count))
                            continue
        except Exception:
            pass
        counts.append(0)
    return counts


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


async def fetch_videos(mal_id: str) -> list:
    """Fetch videos/episodes for a given MAL ID with caching.
    
    Cache TTL: 3h for airing series (has future episode dates), 1 month for finished.
    When TVDB is configured, fetches episodes for ALL seasons sharing the same tvdb_id.
    """
    import logging
    import time as _time

    # Check cache first
    cached = await get_cached_videos(mal_id)
    if cached is not None:
        return cached

    _t0 = _time.time()
    ids = get_ids_from_mal_id(mal_id)
    videos = []

    # Load expired cache to preserve previous translations
    prev_translations = {}  # vid_id -> {"title": ..., "overview": ...}
    rows = await execute("SELECT videos FROM videos_cache WHERE mal_id=?", (mal_id,))
    if rows:
        import orjson as _orjson
        prev_videos = _orjson.loads(rows[0]['videos'])
        for v in prev_videos:
            vid_id = v.get("id")
            if not vid_id:
                continue
            # Only keep if it was actually translated (no _untranslated flags)
            entry = {}
            if v.get("title") and not v.get("_untranslated_title"):
                entry["title"] = v["title"]
            if v.get("overview") and not v.get("_untranslated_overview"):
                entry["overview"] = v["overview"]
            if entry:
                prev_translations[vid_id] = entry
        # Delete expired entry
        await execute("DELETE FROM videos_cache WHERE mal_id=?", (mal_id,))

    # Try TVDB first with multi-season support
    if Config.TVDB_API_KEY and ids.get('tvdb_id'):
        try:
            from app.api.tvdb import get_series_episodes, _build_videos_from_episodes, get_series_extended
            tvdb_id = ids['tvdb_id']

            # Get airs time and country from series record
            _t1 = _time.time()
            series_ext = await get_series_extended(tvdb_id)
            logging.info(f"[TVDB timing] get_series_extended: {_time.time()-_t1:.2f}s")
            airs_time = (series_ext or {}).get("airsTime") or "00:00"
            original_country = (series_ext or {}).get("originalCountry") or ""

            # Get all seasons that share the same tvdb_id
            all_seasons = get_all_seasons_for_tvdb_id(tvdb_id)
            logging.info(f"[TVDB] mal_id={mal_id}, tvdb_id={tvdb_id}, all_seasons={all_seasons}")
            
            # Check if any entry has season info
            has_season_info = any(s.get('season', {}).get('tvdb') for s in all_seasons)
            
            if not all_seasons or not has_season_info:
                # No season mapping — can't split by TVDB seasons
                # If multiple MAL entries share this tvdb_id without season info, skip TVDB
                # (episodes can't be properly attributed to this MAL id)
                if len(all_seasons) > 1:
                    logging.info(f"[TVDB] Skipping - multiple MAL entries without season mapping, falling back to Kitsu")
                    videos = []  # Will fall through to Kitsu fallback below
                else:
                    tvdb_season_num = int(ids['tvdb_season']) if ids.get('tvdb_season') else None
                    _t1 = _time.time()
                    episodes = await get_series_episodes(tvdb_id, season_number=tvdb_season_num, lang="pol")
                    logging.info(f"[TVDB timing] get_series_episodes: {_time.time()-_t1:.2f}s, got {len(episodes)} eps")
                    season_videos = _build_videos_from_episodes(episodes, mal_id, tvdb_season_num, airs_time, original_country)
                    for v in season_videos:
                        v['season'] = v.get('season', 1)
                    videos.extend(season_videos)
            else:
                # Group MAL entries by TVDB season
                from collections import defaultdict
                season_groups = defaultdict(list)
                for season_entry in all_seasons:
                    tvdb_season = season_entry.get('season', {}).get('tvdb')
                    if tvdb_season is not None:
                        season_groups[int(tvdb_season)].append(str(season_entry.get('mal_id', mal_id)))

                for tvdb_season, mal_ids_for_season in sorted(season_groups.items()):
                    _t1 = _time.time()
                    episodes = await get_series_episodes(tvdb_id, season_number=tvdb_season, lang="pol")
                    logging.info(f"[TVDB timing] get_series_episodes s{tvdb_season}: {_time.time()-_t1:.2f}s, got {len(episodes)} eps")

                    if len(mal_ids_for_season) == 1:
                        # Simple case: one MAL entry per season
                        season_videos = _build_videos_from_episodes(episodes, mal_ids_for_season[0], tvdb_season, airs_time, original_country)
                        for v in season_videos:
                            v['season'] = tvdb_season
                        videos.extend(season_videos)
                    else:
                        # Multiple MAL entries share same TVDB season (e.g. Part 1 + Part 2)
                        # Get episode counts from Kitsu/mapping to split correctly
                        ep_counts = await _get_episode_counts(mal_ids_for_season)
                        logging.info(f"[TVDB] Multi-split season {tvdb_season}: mal_ids={mal_ids_for_season}, ep_counts={ep_counts}, total_episodes={len(episodes)}")
                        
                        # Sort episodes by number (already filtered to this season by get_series_episodes)
                        episodes.sort(key=lambda e: e.get("number", 0))
                        # Filter out specials (number <= 0)
                        episodes = [ep for ep in episodes if ep.get("number", 0) > 0]
                        
                        # If all ep_counts are 0, try to split evenly
                        total_known = sum(ep_counts)
                        if total_known == 0:
                            # Fallback: split evenly among all MAL entries
                            per_entry = len(episodes) // len(mal_ids_for_season)
                            ep_counts = [per_entry] * len(mal_ids_for_season)
                            # Give remainder to last entry
                            ep_counts[-1] = len(episodes) - per_entry * (len(mal_ids_for_season) - 1)
                            logging.info(f"[TVDB] No ep_counts available, splitting evenly: {ep_counts}")
                        elif total_known < len(episodes):
                            # Last entry with 0 count gets the remainder
                            for i in range(len(ep_counts) - 1, -1, -1):
                                if ep_counts[i] == 0:
                                    ep_counts[i] = len(episodes) - total_known
                                    break
                        
                        offset = 0
                        global_ep_num = 1  # Continuous episode numbering across all MAL entries in same TVDB season
                        for entry_mal_id, ep_count in zip(mal_ids_for_season, ep_counts):
                            if offset >= len(episodes):
                                break
                            # Slice episodes for this MAL entry
                            entry_episodes = episodes[offset:offset + ep_count]
                            # Use skip_season_filter=True since episodes are already filtered
                            season_videos = _build_videos_from_episodes(entry_episodes, entry_mal_id, tvdb_season, airs_time, original_country, skip_season_filter=True)
                            # Renumber episodes continuously across the whole TVDB season
                            for i, v in enumerate(season_videos):
                                v['episode'] = global_ep_num
                                v['id'] = f"mal:{entry_mal_id}:{i + 1}"
                                v['season'] = tvdb_season
                                global_ep_num += 1
                            videos.extend(season_videos)
                            offset += ep_count
                            logging.info(f"[TVDB] Split: mal:{entry_mal_id} got {len(season_videos)} episodes (offset was {offset - ep_count})")

            if videos:
                # Backdrop fallback for future episodes without thumbnail (no external call needed)
                backdrop = None
                cached_meta = await get_cached_meta(mal_id)
                if cached_meta:
                    backdrop = cached_meta.get('background')
                if not backdrop and series_ext:
                    backdrop = (series_ext or {}).get("image")
                if backdrop:
                    for v in videos:
                        if not v.get('thumbnail'):
                            v['thumbnail'] = backdrop
                
                # Enrich thumbnails from Docchi only if AIRED episodes are missing thumbnails
                aired_missing = [v for v in videos if v.get('available') and not v.get('thumbnail')]
                if aired_missing:
                    _t1 = _time.time()
                    await _enrich_thumbnails({'videos': videos}, mal_id)
                    logging.info(f"[TVDB timing] _enrich_thumbnails: {_time.time()-_t1:.2f}s")
                
                # Check if any episodes have untranslated content
                has_untranslated = any(v.get("_untranslated") for v in videos)
                
                # Restore previous translations for episodes that were already translated
                if prev_translations:
                    for v in videos:
                        vid_id = v.get("id")
                        if vid_id and vid_id in prev_translations:
                            prev = prev_translations[vid_id]
                            if prev.get("title") and v.get("_untranslated_title"):
                                v["title"] = prev["title"]
                                v.pop("_untranslated_title", None)
                                v.pop("_untranslated", None)
                            if prev.get("overview") and v.get("_untranslated_overview"):
                                v["overview"] = prev["overview"]
                                v.pop("_untranslated_overview", None)
                                v.pop("_untranslated", None)
                    # Recount after merge
                    has_untranslated = any(v.get("_untranslated") for v in videos)
                
                logging.info(f"[TVDB] has_untranslated={has_untranslated}, total_videos={len(videos)}, total_time={_time.time()-_t0:.2f}s")
                # Strip general _untranslated flag (keep granular _untranslated_title/_untranslated_overview for cron job)
                for v in videos:
                    v.pop("_untranslated", None)
                
                # Save to cache — no background translation, cron job handles it
                await set_cached_videos(mal_id, videos)
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
