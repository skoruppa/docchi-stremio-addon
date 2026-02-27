"""Shared cache for anime metadata."""
import asyncio
import time
import json
import urllib.parse
from config import Config
from app.utils.anime_mapping import get_ids_from_mal_id
from app.db import execute

CACHE_TTL = 2592000  # 1 month


async def get_cached_meta(mal_id: str):
    """Get cached metadata by MAL ID."""
    rows = await execute("SELECT meta, timestamp FROM meta_cache WHERE mal_id=?", (mal_id,))
    if rows:
        if time.time() - rows[0]['timestamp'] < CACHE_TTL:
            return json.loads(rows[0]['meta'])
        await execute("DELETE FROM meta_cache WHERE mal_id=?", (mal_id,))
    return None


async def set_cached_meta(mal_id: str, meta: dict):
    """Cache metadata by MAL ID with timestamp (videos excluded)."""
    meta_to_cache = {k: v for k, v in meta.items() if k != 'videos'}
    await execute(
        "INSERT OR REPLACE INTO meta_cache (mal_id, meta, timestamp) VALUES (?,?,?)",
        (mal_id, json.dumps(meta_to_cache), int(time.time()))
    )


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
            meta = json.loads(row['meta'])
            cid = mal_id_map[str(row['mal_id'])]
            results[cid] = with_genre_links(meta, is_vip)
            cached_mal_ids.add(str(row['mal_id']))

    missing = [mal_id_map[mid] for mid in mal_ids if mid not in cached_mal_ids]
    if missing:
        fetched = await asyncio.gather(*[fetch_and_cache_meta(cid, is_vip) for cid in missing])
        for cid, (meta, _) in zip(missing, fetched):
            results[cid] = meta

    return results


async def fetch_and_cache_meta(content_id: str, is_vip: bool = False):
    """Fetch metadata from Kitsu API (with MAL fallback) and cache it.
    
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
    
    # Try Kitsu API directly
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

    # Fallback to MAL API if Kitsu fails and MAL_CLIENT_ID is configured
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


async def fetch_videos(mal_id: str) -> list:
    """Fetch fresh videos/episodes for a given MAL ID."""
    ids = get_ids_from_mal_id(mal_id)
    videos = []
    if ids['kitsu_id']:
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
