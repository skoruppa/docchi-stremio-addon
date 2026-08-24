#!/usr/bin/env python3
"""Local translation script — reads untranslated entries from Turso DB and translates them.

Run manually or via system cron:
    .venv/bin/python translate_cron.py

Translates in batches, saves after each chunk. Safe to interrupt and resume.
"""
import asyncio
import logging
import os
import sys
import time

# Setup path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')


async def main():
    from app.db import execute
    from app.utils.translate import batch_translate_episodes, batch_translate_to_polish
    from app.utils.meta_cache import set_cached_videos, set_cached_meta, get_cached_meta
    import orjson

    translated_meta = 0
    translated_videos = 0
    now = int(time.time())

    # 1. Translate ALL untranslated meta descriptions first (in pages of 10)
    logging.info("[Translate] Checking for untranslated meta descriptions...")
    count_rows = await execute(
        r"SELECT COUNT(*) as cnt FROM meta_cache WHERE meta LIKE '%\_untranslated\_description%' ESCAPE '\'"
    )
    total_meta_to_translate = count_rows[0]['cnt'] if count_rows else 0
    logging.info(f"[Translate] Found {total_meta_to_translate} meta entries to translate")
    total_meta_translated = 0
    consecutive_failures = 0
    while True:
        meta_rows = await execute(
            r"SELECT mal_id, meta FROM meta_cache WHERE meta LIKE '%\_untranslated\_description%' ESCAPE '\' LIMIT 5"
        )
        if not meta_rows:
            break

        logging.info(f"[Translate] Found {len(meta_rows)} meta entries to translate")
        texts = []
        metas = []
        for row in meta_rows:
            meta = orjson.loads(row['meta'])
            if meta.get('_untranslated_description'):
                desc = meta.get('description', '')
                if desc:
                    texts.append(desc)
                    metas.append((row['mal_id'], meta))

        if not texts:
            break

        # Deduplicate: translate unique texts only, then map back
        unique_texts = list(dict.fromkeys(texts))  # preserves order, removes dupes
        translations_map = {}
        if len(unique_texts) < len(texts):
            logging.info(f"[Translate] Deduped {len(texts)} -> {len(unique_texts)} unique texts")
        
        unique_translations = await batch_translate_to_polish(unique_texts)
        for text, translated in zip(unique_texts, unique_translations):
            if translated:
                translations_map[text] = translated
        
        # Map translations back to original order
        translations = [translations_map.get(t) for t in texts]

        page_translated = 0
        for (mal_id, meta), translated in zip(metas, translations):
            if translated:
                meta['description'] = translated
                meta.pop('_untranslated_description', None)
                await set_cached_meta(str(mal_id), meta)
                page_translated += 1
                logging.info(f"[Translate] Meta translated: mal:{mal_id}")

        total_meta_translated += page_translated
        if page_translated == 0:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                logging.warning("[Translate] 3 consecutive failures, stopping meta phase")
                break
            logging.warning(f"[Translate] Batch failed ({consecutive_failures}/3), continuing...")
        else:
            consecutive_failures = 0

        # Rate limit pause between pages
        await asyncio.sleep(3)

    translated_meta = total_meta_translated
    if translated_meta:
        logging.info(f"[Translate] Meta phase done: {translated_meta} descriptions translated")
    else:
        logging.info("[Translate] No untranslated meta descriptions found")

    # 2. Translate untranslated video episodes
    logging.info("[Translate] Checking for untranslated video episodes...")
    count_rows = await execute(
        r"SELECT COUNT(*) as cnt FROM videos_cache WHERE videos LIKE '%\_untranslated\_%' ESCAPE '\'"
    )
    total_vids_to_translate = count_rows[0]['cnt'] if count_rows else 0
    logging.info(f"[Translate] Found {total_vids_to_translate} entries with untranslated episodes")
    vid_rows = await execute(
        r"SELECT mal_id, videos FROM videos_cache WHERE videos LIKE '%\_untranslated\_%' ESCAPE '\'"
    )

    # Deduplicate: only process one mal_id per tvdb_id to avoid translating same data multiple times
    from app.utils.anime_mapping import get_ids_from_mal_id
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

    if len(deduplicated_rows) < total_vids_to_translate:
        logging.info(f"[Translate] Deduplicated: {total_vids_to_translate} -> {len(deduplicated_rows)} unique entries")

    for row in deduplicated_rows:
        data = orjson.loads(row['videos'])
        # Handle new dict format {"v": [...], "sp": [...]} and old list format
        if isinstance(data, dict) and "v" in data:
            videos = data["v"]
            season_posters = data.get("sp", [])
        else:
            videos = data if isinstance(data, list) else []
            season_posters = []
        mal_id = str(row['mal_id'])

        # Before translating, check siblings for existing translations
        from app.utils.anime_mapping import get_ids_from_mal_id, get_all_seasons_for_tvdb_id
        ids = get_ids_from_mal_id(mal_id)
        if ids.get('tvdb_id'):
            siblings = get_all_seasons_for_tvdb_id(ids['tvdb_id'])
            for sibling in siblings:
                sib_mal = str(sibling.get('mal_id'))
                if sib_mal and sib_mal != mal_id:
                    sib_rows = await execute('SELECT videos FROM videos_cache WHERE mal_id=?', (sib_mal,))
                    if sib_rows:
                        sib_data = orjson.loads(sib_rows[0]['videos'])
                        sib_vids = sib_data['v'] if isinstance(sib_data, dict) and 'v' in sib_data else (sib_data if isinstance(sib_data, list) else [])
                        # Build lookup: vid_id -> translated fields
                        sib_map = {}
                        for sv in sib_vids:
                            sv_id = sv.get('id')
                            if sv_id:
                                if sv.get('title') and not sv.get('_untranslated_title'):
                                    sib_map.setdefault(sv_id, {})['title'] = sv['title']
                                if sv.get('overview') and not sv.get('_untranslated_overview'):
                                    sib_map.setdefault(sv_id, {})['overview'] = sv['overview']
                        # Apply sibling translations to current videos
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
                                logging.info(f"[Translate] mal:{mal_id} - reused {applied} translations from sibling mal:{sib_mal}")
                                await set_cached_videos(mal_id, videos, 0, season_posters)
                            break  # one sibling is enough

        # Collect all episodes needing translation (after sibling reuse)
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

        logging.info(f"[Translate] mal:{mal_id} - {len(to_translate)} episodes to translate")

        # Translate in chunks of 5
        changed = False
        for chunk_start in range(0, len(to_translate), 5):
            chunk = to_translate[chunk_start:chunk_start + 5]
            episode_data = [ep_data for _, ep_data in chunk]

            results = await batch_translate_episodes(episode_data)

            if not results or all(r.get("title") is None and r.get("overview") is None for r in results):
                logging.warning(f"[Translate] All models failed for mal:{mal_id}, skipping entry for now")
                break

            chunk_ok = 0
            for (vid_idx, _), translated in zip(chunk, results):
                if translated.get("title"):
                    videos[vid_idx]["title"] = translated["title"]
                    videos[vid_idx].pop("_untranslated_title", None)
                    translated_videos += 1
                    chunk_ok += 1
                if translated.get("overview"):
                    videos[vid_idx]["overview"] = translated["overview"]
                    videos[vid_idx].pop("_untranslated_overview", None)
                    translated_videos += 1
                    chunk_ok += 1

            logging.info(f"[Translate] mal:{mal_id} chunk {chunk_start//5+1}: {chunk_ok} fields translated")

            # Save after each chunk
            await set_cached_videos(mal_id, videos, 0, season_posters)
            changed = True

        if changed:
            logging.info(f"[Translate] mal:{mal_id} done")
        
        # Respect rate limits — pause between entries (OpenRouter: 20 RPM free tier)
        await asyncio.sleep(5)

    logging.info(f"[Translate] Finished: {translated_meta} meta + {translated_videos} video fields translated")


if __name__ == "__main__":
    asyncio.run(main())
