import re
import time
import asyncio
import logging
from urllib.parse import unquote

from fastapi import APIRouter, Request, HTTPException

from config import Config
from .manifest import MANIFEST
from app.utils.stream_utils import respond_with
from app.utils.meta_cache import fetch_and_cache_meta, fetch_videos

meta_router = APIRouter()

# In-memory response cache: (meta_id, is_vip) -> (response_data, cache_time, timestamp)
_response_cache: dict[tuple, tuple] = {}
_RESPONSE_CACHE_TTL = 60  # 1 min in-memory response cache
_MAX_RESPONSE_CACHE = 30  # Max entries to prevent unbounded RAM growth


@meta_router.get('/meta/{meta_type}/{meta_id}.json')
async def addon_meta(request: Request, meta_type: str, meta_id: str):
    is_vip = Config.VIP_PATH in request.url.path
    meta_id = unquote(meta_id)

    if meta_type not in MANIFEST['types']:
        raise HTTPException(status_code=404)

    if '_' in meta_id:
        meta_id = meta_id.replace("_", ":")

    # Check in-memory response cache first (avoids all processing)
    cache_key = (meta_id, is_vip)
    if cache_key in _response_cache:
        data, cache_time, ts = _response_cache[cache_key]
        if time.time() - ts < _RESPONSE_CACHE_TTL:
            return respond_with(data, cache_time)
        else:
            del _response_cache[cache_key]

    _t_route = time.time()

    # Extract mal_id early so we can fetch meta and videos in parallel
    from app.utils.meta_cache import _resolve_mal_id
    mal_id = await _resolve_mal_id(meta_id, is_vip)
    if not mal_id:
        return respond_with({'meta': {}, 'message': 'Could not resolve anime ID'})

    logging.info(f"[ROUTE timing] resolve {meta_id} -> mal:{mal_id} in {time.time()-_t_route:.3f}s")

    # Fetch meta and videos in parallel
    meta_task = fetch_and_cache_meta(meta_id, is_vip)
    videos_task = fetch_videos(mal_id)
    (meta, _), videos = await asyncio.gather(meta_task, videos_task)

    logging.info(f"[ROUTE timing] gather done for mal:{mal_id} in {time.time()-_t_route:.3f}s")

    if not meta:
        return respond_with({'meta': {}, 'message': 'Could not fetch anime metadata'})

    meta['id'] = meta_id
    meta['videos'] = videos

    # Recompute 'available' dynamically based on current time (cache may have stale values)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    for v in meta.get('videos', []):
        released = v.get('released')
        if released:
            try:
                ep_date = datetime.fromisoformat(released.replace('Z', '+00:00'))
                v['available'] = ep_date <= now
            except (ValueError, TypeError):
                pass

    # Dynamic cache TTL:
    # - Short (5min) if has untranslated content (cron will translate soon)
    # - Airing: min(1h, seconds until next episode premiere)
    # - Finished and fully translated: 12h
    has_untranslated = (
        meta.get('_untranslated_description') or
        any(v.get('_untranslated_title') or v.get('_untranslated_overview') for v in meta.get('videos', []))
    )
    if has_untranslated:
        cache_time = 300  # 5 min — wait for cron translation
    elif any(not v.get('available', True) for v in meta.get('videos', [])):
        # Airing — cap at time until next episode
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        next_premiere = None
        for v in meta.get('videos', []):
            released = v.get('released')
            if not released:
                continue
            try:
                ep_date = datetime.fromisoformat(released.replace('Z', '+00:00'))
                if ep_date > now and (next_premiere is None or ep_date < next_premiere):
                    next_premiere = ep_date
            except (ValueError, TypeError):
                continue
        if next_premiere:
            seconds_until = int((next_premiere - now).total_seconds())
            cache_time = max(60, min(900, seconds_until))  # max 15 min for airing
        else:
            cache_time = 900  # 15 min — airing but no future date known
    else:
        cache_time = 43200  # 12h — finished, fully translated

    # Store in response cache
    response_data = {'meta': meta}
    if len(_response_cache) >= _MAX_RESPONSE_CACHE:
        # Evict oldest entry
        oldest_key = min(_response_cache, key=lambda k: _response_cache[k][2])
        del _response_cache[oldest_key]
    _response_cache[cache_key] = (response_data, cache_time, time.time())

    return respond_with(response_data, cache_time)
