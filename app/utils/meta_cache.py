"""Shared cache for anime metadata."""
import time
import aiohttp
import asyncio
from config import Config

# Shared in-memory cache for anime metadata (keyed by MAL ID)
# Structure: {mal_id: {'meta': dict, 'timestamp': float}}
_meta_cache = {}
CACHE_TTL = 7200  # 2 hours


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
        # IMDB format: tt2214141 or tt2214141:2
        from app.routes import mapping
        season = int(parts[1]) if len(parts) > 1 else None
        mal_id = mapping.get_mal_id_from_imdb_id(prefix, season)
    elif prefix == 'kitsu' and len(parts) > 1:
        from app.routes import mapping
        mal_id = mapping.get_mal_id_from_kitsu_id(parts[1])
    
    if not mal_id:
        return None, None
    
    # Check cache first
    cached = await get_cached_meta(mal_id)
    if cached:
        return cached, mal_id
    
    # Try Kitsu API first
    try:
        url = f"{Config.KITSU_STREMIO_API_URL}/series/mal:{mal_id}.json"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Extract meta from Kitsu response
                    from app.routes.meta import kitsu_to_meta
                    meta = kitsu_to_meta(data, f"mal:{mal_id}")
                    if meta.get('name'):
                        await set_cached_meta(mal_id, meta)
                        return meta, mal_id
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
                fields='id,title,main_picture,alternative_titles,start_date,end_date,synopsis,mean,num_episodes,start_season,genres,media_type,studios,pictures,background,average_episode_duration'
            )
            if mal_anime:
                meta = await mal_to_meta(mal_anime, f"mal:{mal_id}", mal_id)
                await set_cached_meta(mal_id, meta)
                return meta, mal_id
        except Exception:
            pass
    
    return None, None
