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
