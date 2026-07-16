"""Shared cache for anime metadata."""
import asyncio
import time
import orjson
import urllib.parse
from config import Config
from app.utils.anime_mapping import get_ids_from_mal_id, get_all_seasons_for_tvdb_id
from app.db import execute

CACHE_TTL = 2592000  # 1 month
CACHE_TTL_UPCOMING = 43200  # 12 hours for "Upcoming" series (status may change)
VIDEOS_TTL_AIRING = 10800  # 3 hours for airing series
VIDEOS_TTL_FINISHED = 2592000  # 1 month for finished series
_MAX_MEM_CACHE = 50  # Max entries in memory (reduced for 512MB environments)
_mem_cache: dict[str, tuple[dict, float]] = {}  # mal_id -> (meta, timestamp)
_videos_mem_cache: dict[str, tuple[list, float, int]] = {}  # mal_id -> (videos, timestamp, ttl_override)


def _evict_mem_cache():
    """Evict oldest entries if memory cache exceeds limit."""
    if len(_mem_cache) > _MAX_MEM_CACHE:
        # Remove oldest 25%
        sorted_keys = sorted(_mem_cache, key=lambda k: _mem_cache[k][1])
        for k in sorted_keys[:len(sorted_keys) // 4]:
            del _mem_cache[k]
    if len(_videos_mem_cache) > _MAX_MEM_CACHE:
        sorted_keys = sorted(_videos_mem_cache, key=lambda k: _videos_mem_cache[k][1])
        for k in sorted_keys[:len(sorted_keys) // 4]:
            del _videos_mem_cache[k]


def _meta_ttl(meta: dict) -> int:
    """Get appropriate TTL for a meta entry based on status and completeness."""
    if meta.get('status') == 'Upcoming':
        return CACHE_TTL_UPCOMING
    # Re-fetch sooner if logo is missing (fanart.tv may have added it since)
    if not meta.get('logo'):
        return 86400 * 3  # 3 days
    return CACHE_TTL


async def get_cached_meta(mal_id: str):
    """Get cached metadata by MAL ID."""
    if mal_id in _mem_cache:
        meta, ts = _mem_cache[mal_id]
        if time.time() - ts < _meta_ttl(meta):
            return meta
        del _mem_cache[mal_id]
    rows = await execute("SELECT meta, timestamp FROM meta_cache WHERE mal_id=?", (mal_id,))
    if rows:
        meta = orjson.loads(rows[0]['meta'])
        if time.time() - rows[0]['timestamp'] < _meta_ttl(meta):
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
    _mem_cache[mal_id] = (meta_to_cache, int(time.time()))
    _evict_mem_cache()
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
    return None


async def _get_cached_videos_with_expired(mal_id: str) -> tuple:
    """Get cached videos. Returns (valid_cache, expired_data).
    
    - If cache is valid: returns (videos, None)
    - If cache is expired: returns (None, expired_videos) for reuse as prev_translations
    - If no cache at all: returns (None, None)
    Single DB query instead of two.
    """
    if mal_id in _videos_mem_cache:
        videos, ts, ttl_override = _videos_mem_cache[mal_id]
        ttl = ttl_override if ttl_override else _videos_ttl(videos)
        if time.time() - ts < ttl:
            return videos, None
        del _videos_mem_cache[mal_id]
        return None, videos  # expired but reusable

    rows = await execute("SELECT videos, timestamp FROM videos_cache WHERE mal_id=?", (mal_id,))
    if rows:
        videos = orjson.loads(rows[0]['videos'])
        ts = rows[0]['timestamp']
        ttl = _videos_ttl(videos)
        if time.time() - ts < ttl:
            _videos_mem_cache[mal_id] = (videos, ts, 0)
            return videos, None
        return None, videos  # expired but reusable
    return None, None


async def set_cached_videos(mal_id: str, videos: list, ttl_override: int = 0):
    """Cache videos list by MAL ID. If ttl_override > 0, use that instead of computed TTL."""
    await execute(
        "INSERT OR REPLACE INTO videos_cache (mal_id, videos, timestamp) VALUES (?,?,?)",
        (mal_id, orjson.dumps(videos).decode(), int(time.time()))
    )
    _videos_mem_cache[mal_id] = (videos, int(time.time()), ttl_override)
    _evict_mem_cache()


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


async def _resolve_mal_id(content_id: str, is_vip: bool = False) -> str | None:
    """Resolve content_id to MAL ID without fetching metadata."""
    parts = content_id.split(':')
    prefix = parts[0]

    if prefix == 'mal' and len(parts) > 1:
        return parts[1]
    elif prefix.startswith('tt') and is_vip and len(parts) >= 1:
        from app.routes import mapping
        season = int(parts[1]) if len(parts) > 1 else None
        mal_id = mapping.get_mal_id_from_imdb_id(prefix, season)
        if not mal_id and season and season > 1:
            base_mal_id = mapping.get_mal_id_from_imdb_id(prefix, 1)
            if base_mal_id:
                from app.api.anilist import get_tv_sequel_mal_id
                resolved = await get_tv_sequel_mal_id(int(base_mal_id), season - 1)
                if resolved:
                    mal_id = str(resolved)
        return mal_id
    elif prefix == 'kitsu' and len(parts) > 1:
        from app.routes import mapping
        return mapping.get_mal_id_from_kitsu_id(parts[1])
    return None


async def _resolve_tvdb_via_anilist(mal_id: str, ids: dict) -> dict | None:
    """Resolve tvdb_id for a MAL entry that lacks one.
    
    Tries Simkl API first (fast, 1-2 requests, provides season number directly).
    Falls back to AniList PREQUEL chain if Simkl is unavailable or has no data.
    
    Caches successful results in Redis for future lookups.
    
    Returns dict with tvdb_id and tvdb_season, or None if unable to resolve.
    """
    import logging
    from config import Config

    # Try Simkl first (fast, direct season info)
    if Config.SIMKL_CLIENT_ID:
        from app.api.simkl import get_ids_from_mal
        simkl_result = await get_ids_from_mal(int(mal_id))
        if simkl_result:
            # Cache even without tvdb_id (imdb/tmdb useful for fanart)
            _cache_resolved_mapping(mal_id, simkl_result)
            if simkl_result.get('tvdb_id'):
                return simkl_result

    # Fallback: AniList PREQUEL chain
    from app.api.anilist import get_tv_prequel_chain

    prequels = await get_tv_prequel_chain(int(mal_id))
    if not prequels:
        return None

    for prequel in prequels:
        prequel_mal_id = prequel.get('mal_id')
        if not prequel_mal_id:
            continue

        prequel_ids = get_ids_from_mal_id(str(prequel_mal_id))
        if prequel_ids.get('tvdb_id'):
            prequel_season = int(prequel_ids['tvdb_season']) if prequel_ids.get('tvdb_season') else 1
            resolved_season = prequel_season + prequel['steps']
            logging.info(
                f"[AniList] Resolved mal:{mal_id} -> tvdb:{prequel_ids['tvdb_id']} "
                f"season {resolved_season} (via {prequel['steps']} PREQUEL steps from mal:{prequel_mal_id})"
            )
            result = {
                'tvdb_id': prequel_ids['tvdb_id'],
                'tvdb_season': resolved_season,
                'imdb_id': ids.get('imdb_id') or prequel_ids.get('imdb_id'),
                'tmdb_id': ids.get('tmdb_id') or prequel_ids.get('tmdb_id'),
            }
            _cache_resolved_mapping(mal_id, result)
            return result

    return None


def _cache_resolved_mapping(mal_id: str, resolved: dict):
    """Cache a resolved mapping in Redis for future lookups (TTL 7 days).
    Uses a separate key prefix to avoid being overwritten by load_mapping."""
    import json as _json
    from app.utils.anime_mapping import _redis_client
    if not _redis_client:
        return
    try:
        mini = {'mal_id': int(mal_id)}
        if resolved.get('tvdb_id'):
            mini['tvdb_id'] = resolved['tvdb_id']
        if resolved.get('imdb_id'):
            mini['imdb_id'] = resolved['imdb_id']
        if resolved.get('tmdb_id'):
            mini['themoviedb_id'] = resolved['tmdb_id']
        # Default season to 1 if not provided (single-season series)
        season = resolved.get('tvdb_season') or 1
        mini['season'] = {'tvdb': int(season)}
        _redis_client.setex(f"resolved:mal:{mal_id}", 86400 * 7, _json.dumps(mini))
    except Exception:
        pass


async def _resolve_mal_for_season_via_anilist(known_mal_id: str, steps: int) -> int | None:
    """Resolve MAL ID for a future season by walking SEQUEL chain from a known MAL ID.
    
    Args:
        known_mal_id: MAL ID of a known season (e.g. season 1)
        steps: How many SEQUEL hops to take (e.g. 1 for next season)
    
    Returns:
        MAL ID of the target season, or None if not found.
    """
    from app.api.anilist import get_tv_sequel_mal_id
    return await get_tv_sequel_mal_id(int(known_mal_id), steps)


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
        if not mal_id and season and season > 1:
            base_mal_id = mapping.get_mal_id_from_imdb_id(prefix, 1)
            if base_mal_id:
                from app.api.anilist import get_tv_sequel_mal_id
                resolved = await get_tv_sequel_mal_id(int(base_mal_id), season - 1)
                if resolved:
                    mal_id = str(resolved)
    elif prefix == 'kitsu' and len(parts) > 1:
        from app.routes import mapping
        mal_id = mapping.get_mal_id_from_kitsu_id(parts[1])
    
    if not mal_id:
        return None, None

    import time as _time
    import logging
    _t_start = _time.time()

    def _with_genre_links(meta):
        meta = dict(meta)
        meta['links'] = list(meta.get('links', []))
        build_genre_links(meta, is_vip)
        return meta

    # Check cache first
    cached = await get_cached_meta(mal_id)
    if cached:
        logging.info(f"[META timing] cache hit for mal:{mal_id} in {_time.time()-_t_start:.3f}s")
        return _with_genre_links(cached), mal_id

    logging.info(f"[META timing] cache miss for mal:{mal_id}, fetching...")

    # Check for expired cache to reuse translations
    expired_meta = await _get_expired_meta(mal_id)

    # Try TVDB API first (primary source)
    if Config.TVDB_API_KEY:
        try:
            _t0 = _time.time()
            from app.api.tvdb import get_anime_meta as tvdb_get_meta
            ids = get_ids_from_mal_id(mal_id)
            # If tvdb_id is missing, try to resolve via AniList relations
            if not ids.get('tvdb_id'):
                resolved = await _resolve_tvdb_via_anilist(mal_id, ids)
                if resolved:
                    ids.update(resolved)
                    logging.info(f"[TVDB meta] Resolved tvdb_id via AniList for mal:{mal_id}: tvdb_id={ids['tvdb_id']}, season={ids['tvdb_season']}")
            if ids.get('tvdb_id'):
                tvdb_season = int(ids['tvdb_season']) if ids.get('tvdb_season') is not None else 1
                meta = await tvdb_get_meta(
                    tvdb_id=ids['tvdb_id'],
                    mal_id=mal_id,
                    season_number=tvdb_season,
                    imdb_id=ids.get('imdb_id'),
                    tmdb_id=ids.get('tmdb_id'),
                )
                logging.info(f"[META timing] get_anime_meta: {_time.time()-_t0:.2f}s (total since start: {_time.time()-_t_start:.2f}s)")
                if meta and meta.get('name'):
                    is_untranslated = meta.pop('_untranslated', False)
                    await _fill_genres_from_docchi(meta, mal_id)
                    if is_untranslated:
                        # Check if we have a previous translation from expired cache
                        if expired_meta and expired_meta.get('description') and not expired_meta.get('_untranslated_description'):
                            meta['description'] = expired_meta['description']
                        else:
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
    from app.utils.anime_mapping import get_kitsu_from_mal_id

    async def _fetch_one(session, mid):
        try:
            kitsu_id = get_kitsu_from_mal_id(mid)
            if kitsu_id:
                async with session.get(
                    f"https://kitsu.io/api/edge/anime/{kitsu_id}",
                    headers={"Accept": "application/vnd.api+json", "User-Agent": "Mozilla/5.0"},
                    params={"fields[anime]": "episodeCount"}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return int(data.get("data", {}).get("attributes", {}).get("episodeCount") or 0)
        except Exception:
            pass
        return 0

    async with _aiohttp.ClientSession(timeout=_aiohttp.ClientTimeout(total=5)) as session:
        results = await asyncio.gather(*[_fetch_one(session, mid) for mid in mal_ids])
    return list(results)


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

    # Check cache first (also returns expired data for prev_translations reuse)
    cached, expired_videos = await _get_cached_videos_with_expired(mal_id)
    if cached is not None:
        return cached

    _t0 = _time.time()
    ids = get_ids_from_mal_id(mal_id)
    videos = []

    # Build prev_translations from expired cache (no extra DB query needed)
    prev_translations = {}  # vid_id -> {"title": ..., "overview": ...}
    if expired_videos:
        for v in expired_videos:
            vid_id = v.get("id")
            if not vid_id:
                continue
            entry = {}
            if v.get("title") and not v.get("_untranslated_title"):
                entry["title"] = v["title"]
            if v.get("overview") and not v.get("_untranslated_overview"):
                entry["overview"] = v["overview"]
            if entry:
                prev_translations[vid_id] = entry

    # Try TVDB first with multi-season support
    # If tvdb_id is missing, try to resolve it via AniList relations (PREQUEL chain)
    if Config.TVDB_API_KEY and not ids.get('tvdb_id'):
        resolved = await _resolve_tvdb_via_anilist(mal_id, ids)
        if resolved:
            ids.update(resolved)
            # Default to season 1 if Simkl/AniList didn't provide a season number
            if not ids.get('tvdb_season'):
                ids['tvdb_season'] = 1
            logging.info(f"[TVDB] Resolved tvdb_id via AniList for mal:{mal_id}: tvdb_id={ids['tvdb_id']}, season={ids['tvdb_season']}")

    if Config.TVDB_API_KEY and ids.get('tvdb_id'):
        try:
            from app.api.tvdb import get_series_episodes, _build_videos_from_episodes, get_series_extended
            tvdb_id = ids['tvdb_id']

            # Try to get airs_time/country from cached meta (avoid extra API call)
            cached_meta = await get_cached_meta(mal_id)
            need_extended = not (cached_meta and cached_meta.get("_airsTime"))
            
            if not need_extended:
                airs_time = cached_meta["_airsTime"]
                original_country = cached_meta.get("country") or ""
                series_ext = None

            # Get all seasons that share the same tvdb_id
            all_seasons = get_all_seasons_for_tvdb_id(tvdb_id)
            
            # If current mal_id was resolved via AniList (not in local mapping),
            # add it to all_seasons so it gets its proper season
            current_in_seasons = any(str(s.get('mal_id')) == str(mal_id) for s in all_seasons)
            if not current_in_seasons and ids.get('tvdb_season'):
                # Check if there's already an entry for this season without mal_id — replace it
                target_season = int(ids['tvdb_season'])
                replaced = False
                for i, s in enumerate(all_seasons):
                    if (int(s.get('season', {}).get('tvdb', 0)) == target_season and not s.get('mal_id')):
                        all_seasons[i] = {
                            'mal_id': int(mal_id),
                            'tvdb_id': tvdb_id,
                            'season': {'tvdb': target_season},
                            'kitsu_id': int(ids['kitsu_id']) if ids.get('kitsu_id') else None,
                        }
                        replaced = True
                        break
                if not replaced:
                    all_seasons.append({
                        'mal_id': int(mal_id),
                        'tvdb_id': tvdb_id,
                        'season': {'tvdb': target_season},
                        'kitsu_id': int(ids['kitsu_id']) if ids.get('kitsu_id') else None,
                    })
                all_seasons.sort(key=lambda x: int(x.get('season', {}).get('tvdb', 0) if isinstance(x.get('season'), dict) else 0))
            
            # Resolve missing mal_ids in all_seasons via AniList SEQUEL/PREQUEL chains
            # This ensures all seasons get correct video IDs regardless of which MAL ID is queried
            missing_seasons = [s for s in all_seasons if not s.get('mal_id')]
            if missing_seasons:
                # Find known MAL IDs and their seasons to use as starting points
                known_entries = [(s.get('mal_id'), int(s['season']['tvdb'])) for s in all_seasons if s.get('mal_id') and s.get('season', {}).get('tvdb')]
                if known_entries:
                    from app.api.anilist import get_tv_prequel_chain
                    # For each known MAL ID, walk SEQUEL chain to find mal_ids for later seasons
                    for known_mal, known_season in known_entries:
                        for ms in missing_seasons:
                            ms_season = int(ms.get('season', {}).get('tvdb', 0))
                            steps_needed = ms_season - known_season
                            if steps_needed > 0:
                                # Need to walk SEQUEL chain (forward)
                                resolved_mal = await _resolve_mal_for_season_via_anilist(str(known_mal), steps_needed)
                                if resolved_mal:
                                    ms['mal_id'] = resolved_mal
                                    break
                    # Clean up any still-unresolved entries
                    all_seasons = [s for s in all_seasons if s.get('mal_id')]
            
            logging.info(f"[TVDB] mal_id={mal_id}, tvdb_id={tvdb_id}, all_seasons={all_seasons}")
            
            # Check if current MAL entry has season info
            current_entry = next((s for s in all_seasons if str(s.get('mal_id')) == str(mal_id)), None)
            current_has_season = current_entry and current_entry.get('season', {}).get('tvdb')
            has_season_info = any(s.get('season', {}).get('tvdb') for s in all_seasons)
            
            if not all_seasons or (not current_has_season and not has_season_info):
                # No season mapping at all — try Simkl episode-level TVDB mapping or single season fetch
                if len(all_seasons) > 1 and Config.SIMKL_CLIENT_ID:
                    from app.api.simkl import get_episode_tvdb_mapping
                    simkl_mapping = await get_episode_tvdb_mapping(int(mal_id))
                    if simkl_mapping and simkl_mapping.get('mapping'):
                        # Determine which TVDB seasons this MAL entry covers
                        ep_mapping = simkl_mapping['mapping']
                        covered_seasons = sorted(set(m['season'] for m in ep_mapping.values()))
                        logging.info(f"[Simkl] mal:{mal_id} covers TVDB seasons {covered_seasons} ({len(ep_mapping)} eps)")

                        # Fetch extended for airs_time if needed
                        if need_extended:
                            series_ext = await get_series_extended(tvdb_id)
                            airs_time = (series_ext or {}).get("airsTime") or "00:00"
                            original_country = (series_ext or {}).get("originalCountry") or ""

                        # Fetch all covered seasons from TVDB in parallel
                        season_tasks = [get_series_episodes(tvdb_id, season_number=s, lang="pol") for s in covered_seasons]
                        season_results = await asyncio.gather(*season_tasks)

                        for tvdb_season, episodes in zip(covered_seasons, season_results):
                            season_videos = _build_videos_from_episodes(episodes, mal_id, tvdb_season, airs_time, original_country)
                            for v in season_videos:
                                v['season'] = tvdb_season
                            videos.extend(season_videos)

                        # Set absolute IDs (mal:X:1..N) but keep per-season episode numbers
                        for i, v in enumerate(videos, 1):
                            v['id'] = f"mal:{mal_id}:{i}"

                        logging.info(f"[Simkl] Built {len(videos)} videos for mal:{mal_id} from TVDB via Simkl mapping")
                    else:
                        logging.info(f"[TVDB] Skipping - multiple MAL entries without season mapping, Simkl has no mapping either")
                        videos = []  # Fall through to Kitsu fallback
                elif len(all_seasons) > 1:
                    logging.info(f"[TVDB] Skipping - multiple MAL entries without season mapping, falling back to Kitsu")
                    videos = []  # Will fall through to Kitsu fallback below
                else:
                    tvdb_season_num = int(ids['tvdb_season']) if ids.get('tvdb_season') else None
                    if need_extended:
                        # Fetch extended + episodes in parallel
                        _t1 = _time.time()
                        series_ext, episodes = await asyncio.gather(
                            get_series_extended(tvdb_id),
                            get_series_episodes(tvdb_id, season_number=tvdb_season_num, lang="pol")
                        )
                        airs_time = (series_ext or {}).get("airsTime") or "00:00"
                        original_country = (series_ext or {}).get("originalCountry") or ""
                        logging.info(f"[TVDB timing] extended+episodes parallel: {_time.time()-_t1:.2f}s, got {len(episodes)} eps")
                    else:
                        _t1 = _time.time()
                        episodes = await get_series_episodes(tvdb_id, season_number=tvdb_season_num, lang="pol")
                        logging.info(f"[TVDB timing] get_series_episodes: {_time.time()-_t1:.2f}s, got {len(episodes)} eps")
                    season_videos = _build_videos_from_episodes(episodes, mal_id, tvdb_season_num, airs_time, original_country)
                    for v in season_videos:
                        v['season'] = v.get('season', 1)
                    videos.extend(season_videos)
            else:
                # Current MAL entry lacks season info but others have it
                # Use Simkl episode mapping for the current entry if available
                if not current_has_season and Config.SIMKL_CLIENT_ID:
                    from app.api.simkl import get_episode_tvdb_mapping
                    simkl_mapping = await get_episode_tvdb_mapping(int(mal_id))
                    if simkl_mapping and simkl_mapping.get('mapping'):
                        ep_mapping = simkl_mapping['mapping']
                        covered_seasons = sorted(set(m['season'] for m in ep_mapping.values()))
                        logging.info(f"[Simkl] mal:{mal_id} covers TVDB seasons {covered_seasons} ({len(ep_mapping)} eps)")

                        if need_extended:
                            series_ext = await get_series_extended(tvdb_id)
                            airs_time = (series_ext or {}).get("airsTime") or "00:00"
                            original_country = (series_ext or {}).get("originalCountry") or ""

                        season_tasks = [get_series_episodes(tvdb_id, season_number=s, lang="pol") for s in covered_seasons]
                        season_results = await asyncio.gather(*season_tasks)

                        for tvdb_season, episodes in zip(covered_seasons, season_results):
                            season_videos = _build_videos_from_episodes(episodes, mal_id, tvdb_season, airs_time, original_country)
                            for v in season_videos:
                                v['season'] = tvdb_season
                            videos.extend(season_videos)

                        # Set absolute IDs (mal:269:1..N) but keep per-season episode numbers
                        for i, v in enumerate(videos, 1):
                            v['id'] = f"mal:{mal_id}:{i}"

                        logging.info(f"[Simkl] Built {len(videos)} videos for mal:{mal_id} from TVDB via Simkl mapping")

                # Fall through to regular group-by-season for remaining seasons (e.g. TYBW season 17)
                # that have explicit mapping in all_seasons but weren't covered by Simkl
                if not videos or (videos and has_season_info):
                    from collections import defaultdict
                    season_groups = defaultdict(list)
                    for season_entry in all_seasons:
                        tvdb_season = season_entry.get('season', {}).get('tvdb')
                        if tvdb_season is not None and season_entry.get('mal_id'):
                            season_groups[int(tvdb_season)].append(str(season_entry['mal_id']))

                    # Remove seasons already covered by Simkl mapping
                    if videos:
                        covered = set(v.get('season') for v in videos)
                        season_groups = {s: ids_list for s, ids_list in season_groups.items() if s not in covered}

                    sorted_seasons = sorted(season_groups.items())
                    multi_split_seasons = [
                        (tvdb_season, mal_ids_for_season)
                        for (tvdb_season, mal_ids_for_season) in sorted_seasons
                        if len(mal_ids_for_season) > 1
                    ]
                    all_mal_ids_to_fetch = []
                    for _, mal_ids_for_season in multi_split_seasons:
                        all_mal_ids_to_fetch.extend(mal_ids_for_season)

                    _t1 = _time.time()
                    tasks = [
                        get_series_episodes(tvdb_id, season_number=tvdb_season, lang="pol")
                        for tvdb_season, _ in sorted_seasons
                    ]
                    if need_extended:
                        tasks.append(get_series_extended(tvdb_id))
                    if all_mal_ids_to_fetch:
                        tasks.append(_get_episode_counts(all_mal_ids_to_fetch))

                    results = await asyncio.gather(*tasks)

                    ep_results_end = len(sorted_seasons)
                    season_episode_results = results[:ep_results_end]
                    remaining = results[ep_results_end:]

                    if need_extended:
                        series_ext = remaining[0]
                        remaining = remaining[1:]
                        airs_time = (series_ext or {}).get("airsTime") or "00:00"
                        original_country = (series_ext or {}).get("originalCountry") or ""

                    all_ep_counts = remaining[0] if remaining else []

                    logging.info(f"[TVDB timing] parallel fetch ({len(sorted_seasons)} seasons{' + extended' if need_extended else ''}{' + ep_counts' if all_mal_ids_to_fetch else ''}): {_time.time()-_t1:.2f}s")

                    _ep_count_map = {}
                    if multi_split_seasons:
                        idx = 0
                        for _, mal_ids_for_season in multi_split_seasons:
                            _ep_count_map[id(mal_ids_for_season)] = all_ep_counts[idx:idx+len(mal_ids_for_season)]
                            idx += len(mal_ids_for_season)

                    for (tvdb_season, mal_ids_for_season), episodes in zip(sorted_seasons, season_episode_results):
                        logging.info(f"[TVDB] season {tvdb_season}: got {len(episodes)} eps")

                        if len(mal_ids_for_season) == 1:
                            season_videos = _build_videos_from_episodes(episodes, mal_ids_for_season[0], tvdb_season, airs_time, original_country)
                            for v in season_videos:
                                v['season'] = tvdb_season
                            videos.extend(season_videos)
                        else:
                            ep_counts = _ep_count_map[id(mal_ids_for_season)]
                            logging.info(f"[TVDB] Multi-split season {tvdb_season}: mal_ids={mal_ids_for_season}, ep_counts={ep_counts}, total_episodes={len(episodes)}")

                            episodes.sort(key=lambda e: e.get("number", 0))
                            episodes = [ep for ep in episodes if ep.get("number", 0) > 0]

                            total_known = sum(ep_counts)
                            if total_known == 0:
                                per_entry = len(episodes) // len(mal_ids_for_season)
                                ep_counts = [per_entry] * len(mal_ids_for_season)
                                ep_counts[-1] = len(episodes) - per_entry * (len(mal_ids_for_season) - 1)
                                logging.info(f"[TVDB] No ep_counts available, splitting evenly: {ep_counts}")
                            elif total_known < len(episodes):
                                for i in range(len(ep_counts) - 1, -1, -1):
                                    if ep_counts[i] == 0:
                                        ep_counts[i] = len(episodes) - total_known
                                        break

                            offset = 0
                            global_ep_num = 1
                            for entry_mal_id, ep_count in zip(mal_ids_for_season, ep_counts):
                                if offset >= len(episodes):
                                    break
                                entry_episodes = episodes[offset:offset + ep_count]
                                season_videos = _build_videos_from_episodes(entry_episodes, entry_mal_id, tvdb_season, airs_time, original_country, skip_season_filter=True)
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
                
                # Guard against regression: don't overwrite good cache with worse data
                # If expired cache had titles/thumbnails/overviews and new data doesn't, keep the old
                if expired_videos and videos:
                    old_quality = sum(1 for v in expired_videos if v.get('overview') or (v.get('title') and not v['title'].startswith('Episode ')))
                    new_quality = sum(1 for v in videos if v.get('overview') or (v.get('title') and not v['title'].startswith('Episode ')))
                    if old_quality > 0 and new_quality == 0 and len(videos) <= len(expired_videos):
                        # New data is a regression — TVDB likely returned empty translations
                        logging.warning(f"[TVDB] Regression detected for mal:{mal_id}: old had {old_quality} enriched eps, new has {new_quality}. Keeping old data.")
                        _videos_mem_cache[mal_id] = (expired_videos, int(time.time()), 300)  # short TTL to retry soon
                        asyncio.ensure_future(set_cached_videos(mal_id, expired_videos, 300))
                        return expired_videos
                
                # Save to cache in background (don't block response)
                # Update in-memory cache immediately so next request hits cache
                _videos_mem_cache[mal_id] = (videos, int(time.time()), 0)
                asyncio.ensure_future(set_cached_videos(mal_id, videos))
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
    
    # Backdrop fallback for episodes still without thumbnail
    if videos and any(not v.get('thumbnail') for v in videos):
        cached_meta = await get_cached_meta(mal_id)
        backdrop = cached_meta.get('background') if cached_meta else None
        if backdrop:
            for v in videos:
                if not v.get('thumbnail'):
                    v['thumbnail'] = backdrop

    if videos:
        _videos_mem_cache[mal_id] = (videos, int(time.time()), 0)
        asyncio.ensure_future(set_cached_videos(mal_id, videos))
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
