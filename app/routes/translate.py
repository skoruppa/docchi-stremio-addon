"""Internal endpoint for background translation tasks.

Called by the app itself (fire-and-forget via aiohttp) to translate
videos/meta descriptions without blocking user requests.
"""
import logging
import orjson
from flask import Blueprint, request, abort
from config import Config
from app.utils.meta_cache import get_cached_videos, set_cached_videos, get_cached_meta, set_cached_meta, _mem_cache
from app.utils.translate import batch_translate_to_polish, batch_translate_episodes

translate_bp = Blueprint('translate', __name__)


@translate_bp.route('/internal/translate/videos', methods=['POST'])
async def translate_videos():
    """Translate video overviews and titles for a given mal_id.
    
    Expects JSON: {mal_id: str}
    Loads videos from cache, translates untranslated fields, saves back.
    """
    if request.headers.get('X-Internal-Key') != Config.VIP_PATH:
        abort(403)

    data = request.get_json(force=True)
    mal_id = data.get('mal_id')

    if not mal_id:
        return {'status': 'noop'}, 200

    videos = await get_cached_videos(mal_id)
    if not videos:
        return {'status': 'no_cache'}, 200

    # Collect episodes needing translation
    to_translate = []
    for i, v in enumerate(videos):
        needs_title = v.get("_untranslated_title") and v.get("title")
        needs_overview = v.get("_untranslated_overview") and v.get("overview")
        if needs_title or needs_overview:
            to_translate.append((i, {
                "title": v["title"] if needs_title else None,
                "overview": v["overview"] if needs_overview else None,
            }))

    if not to_translate:
        return {'status': 'already_translated'}, 200

    translated_count = 0
    for chunk_start in range(0, len(to_translate), 10):
        chunk = to_translate[chunk_start:chunk_start + 10]
        episode_data = [ep_data for _, ep_data in chunk]
        try:
            results = await batch_translate_episodes(episode_data)
            for (vid_idx, _), translated in zip(chunk, results):
                if translated.get("title"):
                    videos[vid_idx]["title"] = translated["title"]
                    videos[vid_idx].pop("_untranslated_title", None)
                    translated_count += 1
                if translated.get("overview"):
                    videos[vid_idx]["overview"] = translated["overview"]
                    videos[vid_idx].pop("_untranslated_overview", None)
                    translated_count += 1
        except Exception as e:
            logging.error(f"[TranslateEP] Chunk error: {e}")
        # Save after each chunk
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
    
    Called by GitHub Actions. Finds entries with _untranslated flags and translates them.
    Processes a limited number per run to stay within rate limits.
    """
    # Auth: accept X-Internal-Key header
    if request.headers.get('X-Internal-Key') != Config.VIP_PATH:
        if not request.headers.get('Authorization', '').startswith('Bearer'):
            abort(403)

    import time
    import orjson as _orjson
    from app.db import execute
    from app.utils.translate import batch_translate_episodes, translate_to_polish

    now = int(time.time())
    translated_meta = 0
    translated_videos = 0

    # 1. Translate untranslated meta descriptions
    # Find meta entries with _untranslated_description flag in JSON
    meta_rows = await execute(
        "SELECT mal_id, meta FROM meta_cache WHERE meta LIKE '%_untranslated_description%' LIMIT 5"
    )

    if meta_rows:
        texts = []
        metas = []
        for row in meta_rows:
            meta = _orjson.loads(row['meta'])
            if meta.get('_untranslated_description'):
                desc = meta.get('description', '')
                if desc:
                    texts.append(desc)
                    metas.append((row['mal_id'], meta))

        if texts:
            translations = await batch_translate_to_polish(texts)
            for (mal_id, meta), translated in zip(metas, translations):
                if translated:
                    meta['description'] = translated
                    meta.pop('_untranslated_description', None)
                    await set_cached_meta(str(mal_id), meta)
                    _mem_cache[str(mal_id)] = (meta, now)
                    translated_meta += 1

    # 2. Translate untranslated video episodes (titles + overviews)
    # Scan videos_cache for entries containing _untranslated flags
    vid_rows = await execute(
        "SELECT mal_id, videos FROM videos_cache WHERE videos LIKE '%_untranslated_%' LIMIT 10"
    )

    for row in (vid_rows or []):
        videos = _orjson.loads(row['videos'])
        mal_id = str(row['mal_id'])

        # Collect ALL episodes needing translation for this entry
        to_translate = []
        for i, v in enumerate(videos):
            needs_title = v.get("_untranslated_title") and v.get("title")
            needs_overview = v.get("_untranslated_overview") and v.get("overview")
            if needs_title or needs_overview:
                to_translate.append((i, {
                    "title": v["title"] if needs_title else None,
                    "overview": v["overview"] if needs_overview else None,
                }))

        if not to_translate:
            continue

        logging.info(f"[Cron] Translating mal:{mal_id} - {len(to_translate)} episodes to process")

        # Translate in chunks of 20 episodes
        changed = False
        for chunk_start in range(0, len(to_translate), 20):
            chunk = to_translate[chunk_start:chunk_start + 20]
            episode_data = [ep_data for _, ep_data in chunk]
            results = await batch_translate_episodes(episode_data)

            if not results or all(r.get("title") is None and r.get("overview") is None for r in results):
                # Translation failed for this chunk — skip rest of this entry
                logging.warning(f"[Cron] Translation failed for mal:{mal_id}, skipping remaining")
                break

            for (vid_idx, _), translated in zip(chunk, results):
                if translated.get("title"):
                    videos[vid_idx]["title"] = translated["title"]
                    videos[vid_idx].pop("_untranslated_title", None)
                    translated_videos += 1
                    changed = True
                if translated.get("overview"):
                    videos[vid_idx]["overview"] = translated["overview"]
                    videos[vid_idx].pop("_untranslated_overview", None)
                    translated_videos += 1
                    changed = True

            # Save after each chunk
            if changed:
                await set_cached_videos(mal_id, videos)

        if changed:
            logging.info(f"[Cron] Saved mal:{mal_id} - {translated_videos} fields so far")

    logging.info(f"[Cron] Translated {translated_meta} meta + {translated_videos} video fields")
    return {'status': 'ok', 'meta': translated_meta, 'videos': translated_videos}, 200
