"""Internal endpoint for background translation tasks.

Called by the app itself (fire-and-forget via aiohttp) to translate
videos/meta descriptions without blocking user requests.
"""
import logging
import orjson
from flask import Blueprint, request, abort
from config import Config
from app.utils.meta_cache import get_cached_videos, set_cached_videos, get_cached_meta, set_cached_meta, _mem_cache
from app.utils.translate import batch_translate_to_polish

translate_bp = Blueprint('translate', __name__)


@translate_bp.route('/internal/translate/videos', methods=['POST'])
async def translate_videos():
    """Translate video overviews and titles for a given mal_id.
    
    Expects JSON: {mal_id: str, videos: list}
    Translates all untranslated overviews and titles, saves to cache.
    """
    # Simple auth - only allow internal calls
    if request.headers.get('X-Internal-Key') != Config.VIP_PATH:
        abort(403)

    data = request.get_json(force=True)
    mal_id = data.get('mal_id')
    videos = data.get('videos', [])

    if not mal_id or not videos:
        return {'status': 'noop'}, 200

    to_translate_ov = []
    to_translate_ti = []
    ov_indices = []
    ti_indices = []

    for i, v in enumerate(videos):
        if v.get("overview"):
            to_translate_ov.append(v["overview"])
            ov_indices.append(i)
        if v.get("title") and not v["title"].startswith("Episode "):
            to_translate_ti.append(v["title"])
            ti_indices.append(i)

    translated_count = 0

    # Translate overviews in chunks of 10
    for chunk_start in range(0, len(to_translate_ov), 10):
        chunk = to_translate_ov[chunk_start:chunk_start + 10]
        chunk_indices = ov_indices[chunk_start:chunk_start + 10]
        try:
            translations = await batch_translate_to_polish(chunk)
            for idx, translated in zip(chunk_indices, translations):
                if translated:
                    videos[idx]["overview"] = translated
                    translated_count += 1
        except Exception as e:
            logging.error(f"[TranslateEP] Overview chunk error: {e}")

    # Translate titles in chunks of 10
    for chunk_start in range(0, len(to_translate_ti), 10):
        chunk = to_translate_ti[chunk_start:chunk_start + 10]
        chunk_indices = ti_indices[chunk_start:chunk_start + 10]
        try:
            translations = await batch_translate_to_polish(chunk)
            for idx, translated in zip(chunk_indices, translations):
                if translated:
                    videos[idx]["title"] = translated
                    translated_count += 1
        except Exception as e:
            logging.error(f"[TranslateEP] Title chunk error: {e}")

    # Save to cache
    await set_cached_videos(mal_id, videos)
    logging.info(f"[TranslateEP] Done mal:{mal_id} - {translated_count} translations")
    return {'status': 'ok', 'translated': translated_count}, 200


@translate_bp.route('/internal/translate/meta', methods=['POST'])
async def translate_meta():
    """Translate meta description for a given mal_id.
    
    Expects JSON: {mal_id: str, description: str}
    """
    if request.headers.get('X-Internal-Key') != Config.VIP_PATH:
        abort(403)

    data = request.get_json(force=True)
    mal_id = data.get('mal_id')
    description = data.get('description', '')

    if not mal_id or not description:
        return {'status': 'noop'}, 200

    from app.utils.translate import translate_to_polish
    translated = await translate_to_polish(description)

    if translated:
        # Update cached meta
        cached = await get_cached_meta(mal_id)
        if cached:
            cached['description'] = translated
            await set_cached_meta(mal_id, cached)
            _mem_cache[mal_id] = (cached, __import__('time').time())
        logging.info(f"[TranslateEP] Meta done mal:{mal_id}")
        return {'status': 'ok'}, 200

    return {'status': 'failed'}, 200


@translate_bp.route('/internal/translate/batch_meta', methods=['POST'])
async def translate_batch_meta():
    """Batch translate meta descriptions for multiple mal_ids.
    
    Expects JSON array: [{mal_id: str, description: str}, ...]
    """
    if request.headers.get('X-Internal-Key') != Config.VIP_PATH:
        abort(403)

    items = request.get_json(force=True)
    if not items or not isinstance(items, list):
        return {'status': 'noop', 'results': []}, 200

    texts = [item.get('description', '') for item in items]
    translations = await batch_translate_to_polish(texts)

    results = []
    for item, translated in zip(items, translations):
        mal_id = item.get('mal_id')
        if translated and mal_id:
            # Update cache
            cached = await get_cached_meta(mal_id)
            if cached:
                cached['description'] = translated
                await set_cached_meta(mal_id, cached)
                _mem_cache[mal_id] = (cached, __import__('time').time())
            results.append({'mal_id': mal_id, 'description': translated})

    logging.info(f"[TranslateEP] Batch meta done - {len(results)}/{len(items)} translated")
    return {'status': 'ok', 'results': results}, 200


@translate_bp.route('/internal/cron/translate', methods=['GET'])
async def cron_translate():
    """Cron job: translate untranslated meta descriptions and video episodes.
    
    Called by Vercel Cron every minute. Processes a few items per run.
    Vercel cron sends Authorization header automatically.
    """
    import time
    import orjson as _orjson
    from app.db import execute

    CACHE_TTL = 2592000  # 1 month
    now = int(time.time())
    translated_meta = 0
    translated_videos = 0

    # 1. Find meta entries with short TTL (untranslated - timestamp is manipulated)
    # These have timestamp far in the past (now - CACHE_TTL + 120)
    # So their age is close to CACHE_TTL. Find entries expiring within 5 minutes.
    cutoff_min = now - CACHE_TTL
    cutoff_max = now - CACHE_TTL + 300  # entries that expire within 5 min
    rows = await execute(
        "SELECT mal_id, meta FROM meta_cache WHERE timestamp > ? AND timestamp < ? LIMIT 5",
        (cutoff_min, cutoff_max)
    )

    if rows:
        texts = []
        metas = []
        for row in rows:
            meta = _orjson.loads(row['meta'])
            desc = meta.get('description', '')
            if desc:
                texts.append(desc)
                metas.append((row['mal_id'], meta))

        if texts:
            translations = await batch_translate_to_polish(texts)
            for (mal_id, meta), translated in zip(metas, translations):
                if translated:
                    meta['description'] = translated
                    await set_cached_meta(str(mal_id), meta)
                    _mem_cache[str(mal_id)] = (meta, now)
                    translated_meta += 1

    # 2. Find video entries with short TTL (untranslated)
    vid_rows = await execute(
        "SELECT mal_id, videos FROM videos_cache WHERE timestamp > ? AND timestamp < ? LIMIT 3",
        (cutoff_min, cutoff_max)
    )

    if vid_rows:
        for row in vid_rows:
            videos = _orjson.loads(row['videos'])
            mal_id = str(row['mal_id'])

            # Collect untranslated overviews (first 10)
            to_translate = [(i, v["overview"]) for i, v in enumerate(videos)
                           if v.get("overview") and not any(c > '\u007f' for c in v["overview"][:20])][:10]

            if to_translate:
                texts = [t for _, t in to_translate]
                translations = await batch_translate_to_polish(texts)
                for (idx, _), translated in zip(to_translate, translations):
                    if translated:
                        videos[idx]["overview"] = translated
                        translated_videos += 1

                # Check if all are now translated
                still_untranslated = any(
                    v.get("overview") and not any(c > '\u007f' for c in v["overview"][:20])
                    for v in videos
                )
                if still_untranslated:
                    # Still more to do - keep short TTL
                    await execute(
                        "INSERT OR REPLACE INTO videos_cache (mal_id, videos, timestamp) VALUES (?,?,?)",
                        (mal_id, _orjson.dumps(videos).decode(), cutoff_max)
                    )
                else:
                    # All done - full TTL
                    await set_cached_videos(mal_id, videos)

    logging.info(f"[Cron] Translated {translated_meta} meta + {translated_videos} video descriptions")
    return {'status': 'ok', 'meta': translated_meta, 'videos': translated_videos}, 200
