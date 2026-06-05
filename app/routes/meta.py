import re
from urllib.parse import unquote
from flask import Blueprint, abort, request
from config import Config
from .manifest import MANIFEST
from app.utils.stream_utils import respond_with, cache
from app.utils.meta_cache import fetch_and_cache_meta, fetch_videos

meta_bp = Blueprint('meta', __name__)


@meta_bp.route('/meta/<meta_type>/<meta_id>.json')
async def addon_meta(meta_type: str, meta_id: str):
    import asyncio
    is_vip = Config.VIP_PATH in request.path
    meta_id = unquote(meta_id)

    if meta_type not in MANIFEST['types']:
        abort(404)

    if '_' in meta_id:
        meta_id = meta_id.replace("_", ":")

    # Extract mal_id early so we can fetch meta and videos in parallel
    from app.utils.meta_cache import _resolve_mal_id
    mal_id = await _resolve_mal_id(meta_id, is_vip)
    if not mal_id:
        return respond_with({'meta': {}, 'message': 'Could not resolve anime ID'}), 404

    # Fetch meta and videos in parallel
    meta_task = fetch_and_cache_meta(meta_id, is_vip)
    videos_task = fetch_videos(mal_id)
    (meta, _), videos = await asyncio.gather(meta_task, videos_task)

    if not meta:
        return respond_with({'meta': {}, 'message': 'Could not fetch anime metadata'}), 404

    meta['id'] = meta_id
    meta['videos'] = videos

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
            cache_time = max(60, min(10800, seconds_until))
        else:
            cache_time = 10800
    else:
        cache_time = 43200  # 12h — finished, fully translated

    return respond_with({'meta': meta}, cache_time)
