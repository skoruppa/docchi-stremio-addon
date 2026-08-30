"""Internal endpoint for background translation tasks.

Called by the app itself (fire-and-forget via aiohttp) to translate
videos/meta descriptions without blocking user requests.
"""
import logging
import orjson
from fastapi import APIRouter, Request, HTTPException
from config import Config
from app.utils.meta_cache import get_cached_videos, set_cached_videos, get_cached_meta, set_cached_meta, _mem_cache
from app.utils.translate import batch_translate_to_polish, batch_translate_episodes

translate_router = APIRouter()


def _check_internal_auth(request: Request):
    """Verify internal API key. Accepts INTERNAL_API_KEY or falls back to VIP_PATH for backward compat."""
    key = request.headers.get('X-Internal-Key', '')
    if Config.INTERNAL_API_KEY and key == Config.INTERNAL_API_KEY:
        return
    if not Config.INTERNAL_API_KEY and key == Config.VIP_PATH:
        return  # backward compat: if INTERNAL_API_KEY not set, accept VIP_PATH
    raise HTTPException(status_code=403)


@translate_router.post('/internal/translate/videos')
async def translate_videos(request: Request):
    """Translate video overviews and titles for a given mal_id.

    Expects JSON: {mal_id: str}
    Loads videos from cache, translates untranslated fields, saves back.
    """
    _check_internal_auth(request)

    data = await request.json()
    mal_id = data.get('mal_id')

    if not mal_id:
        return {'status': 'noop'}

    videos = await get_cached_videos(mal_id)
    if not videos:
        return {'status': 'no_cache'}

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
        return {'status': 'already_translated'}

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
    return {'status': 'ok', 'translated': translated_count}


@translate_router.post('/internal/translate/meta')
async def translate_meta(request: Request):
    """Translate meta description for a given mal_id.

    Expects JSON: {mal_id: str, description: str}
    """
    _check_internal_auth(request)

    data = await request.json()
    mal_id = data.get('mal_id')
    description = data.get('description', '')

    if not mal_id or not description:
        return {'status': 'noop'}

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
        return {'status': 'ok'}

    return {'status': 'failed'}


@translate_router.post('/internal/translate/batch_meta')
async def translate_batch_meta(request: Request):
    """Batch translate meta descriptions for multiple mal_ids.

    Expects JSON array: [{mal_id: str, description: str}, ...]
    """
    _check_internal_auth(request)

    items = await request.json()
    if not items or not isinstance(items, list):
        return {'status': 'noop', 'results': []}

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
    return {'status': 'ok', 'results': results}


@translate_router.get('/internal/cron/translate')
async def cron_translate(request: Request):
    """Cron job: translate untranslated meta descriptions and video episodes.

    Called by GitHub Actions. Finds entries with _untranslated flags and translates them.
    Processes in batches with rate limiting. Safe to call repeatedly.
    """
    _check_internal_auth(request)

    import asyncio
    import time
    import orjson as _orjson
    from app.db import execute
    from app.utils.translate import batch_translate_episodes, batch_translate_to_polish
    from app.utils.anime_mapping import get_ids_from_mal_id, get_all_seasons_for_tvdb_id

    now = int(time.time())
    translated_meta = 0
    translated_videos = 0
    consecutive_failures = 0

    # 1. Translate ALL untranslated meta descriptions (in pages of 5)
    while True:
        meta_rows = await execute(
            r"SELECT mal_id, meta FROM meta_cache WHERE meta LIKE '%\_untranslated\_description%' ESCAPE '\' LIMIT 5"
        )
        if not meta_rows:
            break

        texts = []
        metas = []
        for row in meta_rows:
            meta = _orjson.loads(row['meta'])
            if meta.get('_untranslated_description'):
                desc = meta.get('description', '')
                if desc:
                    texts.append(desc)
                    metas.append((row['mal_id'], meta))

        if not texts:
            break

        # Deduplicate texts
        unique_texts = list(dict.fromkeys(texts))
        unique_translations = await batch_translate_to_polish(unique_texts)
        translations_map = {}
        for text, translated in zip(unique_texts, unique_translations):
            if translated:
                translations_map[text] = translated
        translations = [translations_map.get(t) for t in texts]

        page_translated = 0
        for (mal_id, meta), translated in zip(metas, translations):
            if translated:
                meta['description'] = translated
                meta.pop('_untranslated_description', None)
                await set_cached_meta(str(mal_id), meta)
                _mem_cache[str(mal_id)] = (meta, now)
                page_translated += 1
                translated_meta += 1

        if page_translated == 0:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                break
        else:
            consecutive_failures = 0

        await asyncio.sleep(3)

    # 2. Translate untranslated video episodes
    vid_rows = await execute(
        r"SELECT mal_id, videos FROM videos_cache WHERE videos LIKE '%\_untranslated\_%' ESCAPE '\'"
    )

    # Deduplicate: only process one mal_id per tvdb_id
    seen_tvdb_ids = set()
    deduplicated_rows = []
    for row in (vid_rows or []):
        mal_id = str(row['mal_id'])
        ids = get_ids_from_mal_id(mal_id)
        tvdb_id = ids.get('tvdb_id')
        if tvdb_id:
            if tvdb_id in seen_tvdb_ids:
                continue
            seen_tvdb_ids.add(tvdb_id)
        deduplicated_rows.append(row)

    for row in deduplicated_rows:
        data = _orjson.loads(row['videos'])
        # Handle new dict format {"v": [...], "sp": [...]} and old list format
        if isinstance(data, dict) and "v" in data:
            videos = data["v"]
            season_posters = data.get("sp", [])
        else:
            videos = data if isinstance(data, list) else []
            season_posters = []
        mal_id = str(row['mal_id'])

        # Before translating, check siblings for existing translations
        ids = get_ids_from_mal_id(mal_id)
        if ids.get('tvdb_id'):
            siblings = get_all_seasons_for_tvdb_id(ids['tvdb_id'])
            for sibling in siblings:
                sib_mal = str(sibling.get('mal_id'))
                if sib_mal and sib_mal != mal_id:
                    sib_rows = await execute('SELECT videos FROM videos_cache WHERE mal_id=?', (sib_mal,))
                    if sib_rows:
                        sib_data = _orjson.loads(sib_rows[0]['videos'])
                        sib_vids = sib_data['v'] if isinstance(sib_data, dict) and 'v' in sib_data else (sib_data if isinstance(sib_data, list) else [])
                        sib_map = {}
                        for sv in sib_vids:
                            sv_id = sv.get('id')
                            if sv_id:
                                if sv.get('title') and not sv.get('_untranslated_title'):
                                    sib_map.setdefault(sv_id, {})['title'] = sv['title']
                                if sv.get('overview') and not sv.get('_untranslated_overview'):
                                    sib_map.setdefault(sv_id, {})['overview'] = sv['overview']
                        if sib_map:
                            applied = 0
                            for v in videos:
                                vid_id = v.get('id')
                                if vid_id and vid_id in sib_map:
                                    sib = sib_map[vid_id]
                                    if sib.get('title') and v.get('_untranslated_title'):
                                        v['title'] = sib['title']
                                        v.pop('_untranslated_title', None)
                                        applied += 1
                                    if sib.get('overview') and v.get('_untranslated_overview'):
                                        v['overview'] = sib['overview']
                                        v.pop('_untranslated_overview', None)
                                        applied += 1
                            if applied:
                                logging.info(f"[Cron] mal:{mal_id} - reused {applied} translations from sibling mal:{sib_mal}")
                                await set_cached_videos(mal_id, videos, 0, season_posters)
                            break

        # Collect episodes needing translation (after sibling reuse)
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

        logging.info(f"[Cron] Translating mal:{mal_id} - {len(to_translate)} episodes")

        # Translate in chunks of 5
        changed = False
        for chunk_start in range(0, len(to_translate), 5):
            chunk = to_translate[chunk_start:chunk_start + 5]
            episode_data = [ep_data for _, ep_data in chunk]
            results = await batch_translate_episodes(episode_data)

            # Check content refusal
            content_refused = results and any(r.get("title") == "__CONTENT_REFUSED__" for r in results)
            all_failed = not results or all(r.get("title") is None and r.get("overview") is None for r in results)

            if content_refused:
                # Retry with uncensored model
                from app.utils.translate import _openrouter_request, BATCH_TRANSLATE_PROMPT
                parts = []
                for ep in episode_data:
                    title = ep.get("title") or ""
                    overview = ep.get("overview") or ""
                    parts.append(f"TITLE: {title if title else 'empty'}\nDESC: {overview if overview else 'empty'}")
                prompt = BATCH_TRANSLATE_PROMPT + "\n---\n".join(parts)
                raw = await _openrouter_request(prompt, model_override="cognitivecomputations/dolphin-mistral-24b-venice-edition")
                if raw and raw != "__CONTENT_REFUSED__":
                    blocks = raw.split("---")
                    results = []
                    for idx in range(len(episode_data)):
                        if idx < len(blocks):
                            block = blocks[idx].strip()
                            title_line = None
                            desc_line = None
                            for line in block.split("\n"):
                                line = line.strip()
                                if not line:
                                    continue
                                if line.upper().startswith("TITLE:") or line.upper().startswith("TYTUŁ:") or line.upper().startswith("TITUL:"):
                                    sep = line.index(":") + 1
                                    title_line = line[sep:].strip()
                                elif line.upper().startswith("DESC:") or line.upper().startswith("OPIS:"):
                                    sep = line.index(":") + 1
                                    desc_line = line[sep:].strip()
                            if title_line and title_line.lower() in ("empty", "puste", "pusty", "brak"):
                                title_line = None
                            if desc_line and desc_line.lower() in ("empty", "puste", "pusty", "brak"):
                                desc_line = None
                            results.append({"title": title_line, "overview": desc_line})
                        else:
                            results.append({"title": None, "overview": None})
                    all_failed = all(r.get("title") is None and r.get("overview") is None for r in results)
                else:
                    all_failed = True

            if all_failed:
                logging.warning(f"[Cron] All models failed for mal:{mal_id}, skipping")
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

            if changed:
                await set_cached_videos(mal_id, videos, 0, season_posters)

        if changed:
            logging.info(f"[Cron] Done mal:{mal_id}")

        await asyncio.sleep(5)

    logging.info(f"[Cron] Finished: {translated_meta} meta + {translated_videos} video fields")
    return {'status': 'ok', 'meta': translated_meta, 'videos': translated_videos}
