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

    # 1. Translate untranslated meta descriptions
    logging.info("[Translate] Checking for untranslated meta descriptions...")
    meta_rows = await execute(
        "SELECT mal_id, meta FROM meta_cache WHERE meta LIKE '%_untranslated_description%' LIMIT 20"
    )

    if meta_rows:
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

        if texts:
            translations = await batch_translate_to_polish(texts)
            for (mal_id, meta), translated in zip(metas, translations):
                if translated:
                    meta['description'] = translated
                    meta.pop('_untranslated_description', None)
                    await set_cached_meta(str(mal_id), meta)
                    translated_meta += 1
                    logging.info(f"[Translate] Meta translated: mal:{mal_id}")
    else:
        logging.info("[Translate] No untranslated meta descriptions found")

    # 2. Translate untranslated video episodes
    logging.info("[Translate] Checking for untranslated video episodes...")
    vid_rows = await execute(
        "SELECT mal_id, videos FROM videos_cache WHERE videos LIKE '%_untranslated_%'"
    )

    if not vid_rows:
        logging.info("[Translate] No untranslated videos found")
    else:
        logging.info(f"[Translate] Found {len(vid_rows)} entries with untranslated episodes")

    for row in (vid_rows or []):
        videos = orjson.loads(row['videos'])
        mal_id = str(row['mal_id'])

        # Collect all episodes needing translation
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
            await set_cached_videos(mal_id, videos)
            changed = True

        if changed:
            logging.info(f"[Translate] mal:{mal_id} done")
        
        # Respect rate limits — pause between entries (OpenRouter: 20 RPM free tier)
        await asyncio.sleep(5)

    logging.info(f"[Translate] Finished: {translated_meta} meta + {translated_videos} video fields translated")


if __name__ == "__main__":
    asyncio.run(main())
