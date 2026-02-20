"""Shared cache for anime metadata."""
import time
import json
import os
import aiohttp
import asyncio
from config import Config

_meta_cache = {}
CACHE_TTL = 43200  # 12 hours
_CACHE_FILE = '/tmp/meta_cache.json'


def _load_cache_from_file():
    try:
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


_meta_cache = _load_cache_from_file()


async def get_cached_meta(mal_id: str):
    """Get cached metadata by MAL ID."""
    entry = _meta_cache.get(mal_id)
    if entry:
        # Check if cache entry is still valid
        if time.time() - entry['timestamp'] < CACHE_TTL:
            return entry['meta']
        else:
            # Remove expired entry
            del _meta_cache[mal_id]
    return None


async def set_cached_meta(mal_id: str, meta: dict):
    """Cache metadata by MAL ID with timestamp."""
    _meta_cache[mal_id] = {
        'meta': meta,
        'timestamp': time.time()
    }
    try:
        with open(_CACHE_FILE, 'w') as f:
            json.dump(_meta_cache, f)
    except Exception:
        pass


def _fix_video_ids(meta: dict, mal_id: str):
    """Convert video IDs to mal: format."""
    if meta.get('videos') and mal_id:
        for item in meta['videos']:
            video_id = item.get('id', '')
            if ':' in video_id:
                episode = video_id.split(':')[-1]
                item['id'] = f"mal:{mal_id}:{episode}"


async def _fix_links(meta: dict, mal_id: str):
    """Fix links: remove Genres (rebuilt dynamically), convert Franchise kitsu IDs to mal, replace imdb with docchi."""
    import re
    from app.routes import mapping
    from app.utils.anime_mapping import get_slug_from_mal_id

    other_links = []
    for link in meta.get('links', []):
        if link.get('category') == 'Genres':
            continue
        if link.get('category') == 'Franchise':
            url = link.get('url', '')
            match = re.search(r'kitsu:(\d+)', url)
            if match:
                franchise_mal_id = mapping.get_mal_id_from_kitsu_id(match.group(1))
                if franchise_mal_id:
                    link['url'] = url.replace(f'kitsu:{match.group(1)}', f'mal:{franchise_mal_id}')
                    other_links.append(link)
            else:
                other_links.append(link)
            continue
        if link.get('category') == 'imdb':
            slug = await get_slug_from_mal_id(mal_id)
            if slug:
                link['url'] = f"https://docchi.pl/production/as/{slug}"
        other_links.append(link)
    meta['links'] = other_links


def build_genre_links(meta: dict, is_vip: bool = False, catalog_id: str = 'season'):
    """Build genre links for meta using the correct manifest URL and catalog."""
    from app.routes.manifest import genres as manifest_genres
    manifest_path = f"{Config.VIP_PATH}/manifest.json" if is_vip else "manifest.json"
    import urllib.parse
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

(content_id: str, is_vip: bool = False):
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
        # IMDB format: tt2214141 or tt2214141:2
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
    
    # Try Kitsu API first
    try:
        url = f"{Config.KITSU_STREMIO_API_URL}/series/mal:{mal_id}.json"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    from app.routes.meta import kitsu_to_meta
                    meta = kitsu_to_meta(data, f"mal:{mal_id}")
                    if meta.get('name'):
                        _fix_video_ids(meta, mal_id)
                        await _fix_links(meta, mal_id)
                        await set_cached_meta(mal_id, meta)
                        return _with_genre_links(meta), mal_id
    except Exception:
        pass
    
    # Fallback to MAL API if Kitsu fails and MAL_CLIENT_ID is configured
    if Config.MAL_CLIENT_ID:
        try:
            from pyMALv2.auth import Authorization
            from pyMALv2.services.anime_service.anime_service import AnimeService
            from app.routes.meta import mal_to_meta
            
            auth = Authorization()
            auth.client_id = Config.MAL_CLIENT_ID
            anime_service = AnimeService(auth)
            
            mal_anime = await asyncio.to_thread(
                anime_service.get,
                int(mal_id),
                fields='id,title,main_picture,alternative_titles,start_date,end_date,synopsis,mean,rank,popularity,num_list_users,num_scoring_users,nsfw,created_at,updated_at,media_type,status,genres,my_list_status,num_episodes,start_season,broadcast,source,average_episode_duration,rating,pictures,background,related_anime,related_manga,recommendations,studios,statistics'
            )
            if mal_anime:
                meta = await mal_to_meta(mal_anime, f"mal:{mal_id}", mal_id)
                _fix_video_ids(meta, mal_id)
                await _fix_links(meta, mal_id)
                await set_cached_meta(mal_id, meta)
                return _with_genre_links(meta), mal_id
        except Exception:
            pass
    
    return None, None
