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

    # Ensure translation_queue exists and is populated
    await execute("""
        CREATE TABLE IF NOT EXISTS translation_queue (
            mal_id TEXT PRIMARY KEY,
            queue_type TEXT NOT NULL DEFAULT 'both',
            tvdb_id INTEGER,
            created_at INTEGER
        )
    """)
    try:
        await execute("ALTER TABLE translation_queue ADD COLUMN tvdb_id INTEGER")
    except Exception:
        pass
    existing = await execute("SELECT COUNT(*) as cnt FROM translation_queue")
    if not existing or existing[0]['cnt'] == 0:
        logging.info("[Translate] Populating translation_queue from existing cache...")
        await execute(
            r"INSERT OR IGNORE INTO translation_queue (mal_id, queue_type, created_at) "
            r"SELECT mal_id, 'meta', timestamp FROM meta_cache WHERE meta LIKE '%_untranslated_description%'"
        )
        await execute(
            r"INSERT OR IGNORE INTO translation_queue (mal_id, queue_type, created_at) "
            r"SELECT mal_id, 'videos', timestamp FROM videos_cache WHERE videos LIKE '%_untranslated_%'"
        )
        count_after = await execute("SELECT COUNT(*) as cnt FROM translation_queue")
        logging.info(f"[Translate] Queue populated: {count_after[0]['cnt']} entries")

    # 1. Translate ALL untranslated meta descriptions first (in pages of 10)
    logging.info("[Translate] Checking for untranslated meta descriptions...")
    count_rows = await execute(
        "SELECT COUNT(*) as cnt FROM translation_queue WHERE queue_type='meta'"
    )
    total_meta_to_translate = count_rows[0]['cnt'] if count_rows else 0
    logging.info(f"[Translate] Found {total_meta_to_translate} meta entries to translate")
    total_meta_translated = 0
    consecutive_failures = 0
    while True:
        meta_rows = await execute(
            "SELECT m.mal_id, m.meta FROM meta_cache m INNER JOIN translation_queue q ON m.mal_id=q.mal_id WHERE q.queue_type='meta' LIMIT 5"
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
        "SELECT COUNT(*) as cnt FROM translation_queue WHERE queue_type='videos'"
    )
    total_vids_to_translate = count_rows[0]['cnt'] if count_rows else 0
    logging.info(f"[Translate] Found {total_vids_to_translate} entries with untranslated episodes")

    # Fetch deduplicated: one mal_id per tvdb_id (MIN picks the first), plus all without tvdb_id
    vid_rows = await execute(
        "SELECT v.mal_id, v.videos FROM videos_cache v INNER JOIN ("
        "  SELECT MIN(mal_id) as mal_id FROM translation_queue WHERE queue_type='videos' AND tvdb_id IS NOT NULL GROUP BY tvdb_id"
        "  UNION ALL"
        "  SELECT mal_id FROM translation_queue WHERE queue_type='videos' AND tvdb_id IS NULL"
        ") q ON v.mal_id=q.mal_id"
    )

    if vid_rows and len(vid_rows) < total_vids_to_translate:
        logging.info(f"[Translate] Deduplicated: {total_vids_to_translate} -> {len(vid_rows)} unique entries")

    for row in (vid_rows or []):
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

            # Check if content was refused (NSFW filter) vs general failure
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
                    logging.info(f"[Translate] Uncensored model succeeded for mal:{mal_id}")
                    all_failed = all(r.get("title") is None and r.get("overview") is None for r in results)
                else:
                    all_failed = True

            if all_failed:
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

    # Cleanup: remove stale queue entries where videos are already translated
    stale = await execute(
        "SELECT q.mal_id, v.videos FROM translation_queue q "
        "INNER JOIN videos_cache v ON q.mal_id=v.mal_id "
        "WHERE q.queue_type='videos'"
    )
    cleaned = 0
    for row in (stale or []):
        data = orjson.loads(row['videos'])
        vids = data['v'] if isinstance(data, dict) and 'v' in data else (data if isinstance(data, list) else [])
        if not any(v.get('_untranslated_title') or v.get('_untranslated_overview') for v in vids):
            await execute("DELETE FROM translation_queue WHERE mal_id=? AND queue_type='videos'", (str(row['mal_id']),))
            cleaned += 1
    if cleaned:
        logging.info(f"[Translate] Cleaned {cleaned} stale queue entries")

    logging.info(f"[Translate] Finished: {translated_meta} meta + {translated_videos} video fields translated")


async def translate_single(mal_id: str, force: bool = False):
    """Translate a single mal_id's meta description and videos.
    
    With --force: re-translates everything (even already translated content)
    using the original English text fetched from TVDB.
    Without --force: only translates entries marked as _untranslated.
    """
    from app.db import execute
    from app.utils.translate import batch_translate_episodes, translate_to_polish
    from app.utils.meta_cache import set_cached_videos, set_cached_meta, get_cached_meta
    import orjson

    logging.info(f"[Translate] Single mode: mal:{mal_id} (force={force})")

    # --- 1. Meta description ---
    meta_rows = await execute('SELECT meta FROM meta_cache WHERE mal_id=?', (mal_id,))
    if meta_rows:
        meta = orjson.loads(meta_rows[0]['meta'])
        needs_meta = force or meta.get('_untranslated_description')
        if needs_meta:
            if force:
                # Fetch original English description from TVDB/source
                eng_desc = await _fetch_english_description(mal_id)
                if eng_desc:
                    logging.info(f"  [Meta] English desc: {eng_desc[:80]}...")
                    translated = await translate_to_polish(eng_desc)
                else:
                    logging.warning(f"  [Meta] Could not fetch English description, using cached")
                    translated = await translate_to_polish(meta.get('description', ''))
            else:
                translated = await translate_to_polish(meta.get('description', ''))
            if translated:
                meta['description'] = translated
                meta.pop('_untranslated_description', None)
                await set_cached_meta(mal_id, meta)
                logging.info(f"  [Meta] Translated: {translated[:80]}...")
            else:
                logging.warning(f"  [Meta] Translation failed")
        else:
            logging.info(f"  [Meta] Already translated, skipping (use --force to re-translate)")
    else:
        logging.warning(f"  [Meta] No meta cache for mal:{mal_id}")

    # --- 2. Videos/episodes ---
    rows = await execute('SELECT videos, timestamp FROM videos_cache WHERE mal_id=?', (mal_id,))
    if not rows:
        logging.error(f"  [Videos] Not found in videos_cache")
        return

    import time
    age_min = (time.time() - rows[0]['timestamp']) / 60
    data = orjson.loads(rows[0]['videos'])
    videos = data['v'] if isinstance(data, dict) and 'v' in data else data
    season_posters = data.get('sp', []) if isinstance(data, dict) else []

    logging.info(f"  [Videos] Cache age: {age_min:.0f}min, {len(videos)} eps")

    if force:
        # Fetch original English episodes from TVDB
        eng_episodes = await _fetch_english_episodes(mal_id)
        eng_map = {}  # vid_id -> {"title": ..., "overview": ...}
        for ep in eng_episodes:
            vid_id = ep.get('id')
            if vid_id:
                eng_map[vid_id] = ep

    # Show current state
    for v in videos:
        ut = 'U' if v.get('_untranslated_title') else ' '
        uo = 'U' if v.get('_untranslated_overview') else ' '
        logging.info(f"  {v.get('id')} T:{ut} O:{uo} \"{v.get('title', '')[:50]}\"")

    # Collect episodes to translate
    to_translate = []
    for i, v in enumerate(videos):
        if force:
            # Use English source text when forcing
            vid_id = v.get('id')
            eng = eng_map.get(vid_id, {}) if force else {}
            title_src = eng.get('title') or v.get('title')
            overview_src = eng.get('overview') or v.get('overview')
            if title_src or overview_src:
                to_translate.append((i, {
                    "title": title_src,
                    "overview": overview_src,
                }))
        else:
            needs_title = v.get("_untranslated_title") and v.get("title")
            needs_overview = v.get("_untranslated_overview") and v.get("overview")
            if needs_title or needs_overview:
                to_translate.append((i, {
                    "title": v["title"] if needs_title else None,
                    "overview": v["overview"] if needs_overview else None,
                }))

    if not to_translate:
        logging.info("  Nothing to translate!")
        return

    logging.info(f"  Translating {len(to_translate)} episodes...")

    for chunk_start in range(0, len(to_translate), 5):
        chunk = to_translate[chunk_start:chunk_start + 5]
        episode_data = [ep_data for _, ep_data in chunk]
        results = await batch_translate_episodes(episode_data)

        for (vid_idx, _), translated in zip(chunk, results):
            if translated.get("title"):
                videos[vid_idx]["title"] = translated["title"]
                videos[vid_idx].pop("_untranslated_title", None)
                logging.info(f"    Translated: {videos[vid_idx]['id']} -> \"{translated['title'][:50]}\"")
            if translated.get("overview"):
                videos[vid_idx]["overview"] = translated["overview"]
                videos[vid_idx].pop("_untranslated_overview", None)

        # Save after each chunk
        await set_cached_videos(mal_id, videos, 0, season_posters)
        await asyncio.sleep(3)

    logging.info(f"  Saved. Verifying...")

    # Read back and verify
    rows2 = await execute('SELECT videos FROM videos_cache WHERE mal_id=?', (mal_id,))
    data2 = orjson.loads(rows2[0]['videos'])
    vids2 = data2['v'] if isinstance(data2, dict) and 'v' in data2 else data2
    n_u = sum(1 for v in vids2 if v.get('_untranslated_title') or v.get('_untranslated_overview'))
    logging.info(f"  After save: {n_u} still untranslated")
    for v in vids2:
        ut = 'U' if v.get('_untranslated_title') else ' '
        logging.info(f"  {v.get('id')} T:{ut} \"{v.get('title', '')[:50]}\"")


def _clean_description(text: str) -> str:
    """Clean HTML tags and source attribution from description text."""
    import re
    if not text:
        return text
    # Remove HTML tags
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    # Remove source attribution like "(Source: Crunchyroll)" or "(Źródło: ...)"
    text = re.sub(r'\s*\((?:Source|Źródło|Written by)[^)]*\)\s*$', '', text, flags=re.IGNORECASE)
    # Clean up whitespace
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text


async def _fetch_english_description(mal_id: str) -> str | None:
    """Fetch the original English description for a MAL ID.
    
    Tries sources in order: TVDB → TMDB → AniList → MAL.
    """
    import aiohttp
    from app.utils.anime_mapping import load_mapping, get_ids_from_mal_id
    from config import Config
    load_mapping()
    ids = get_ids_from_mal_id(mal_id)

    # 1. TVDB
    if Config.TVDB_API_KEY and ids.get('tvdb_id'):
        try:
            from app.api.tvdb import _api_get
            data = await _api_get(f"/series/{ids['tvdb_id']}/translations/eng")
            if data and data.get('data', {}).get('overview'):
                return _clean_description(data['data']['overview'])
        except Exception:
            pass

    # 2. TMDB
    tmdb_id = ids.get('tmdb_id')
    if Config.TMDB_API_KEY and tmdb_id:
        if isinstance(tmdb_id, list):
            tmdb_id = tmdb_id[0] if tmdb_id else None
        if tmdb_id:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as sess:
                    async with sess.get(
                        f"https://api.themoviedb.org/3/tv/{tmdb_id}",
                        params={"api_key": Config.TMDB_API_KEY, "language": "en-US"}
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get('overview'):
                                return _clean_description(data['overview'])
            except Exception:
                pass

    # 3. AniList
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as sess:
            query = 'query ($idMal: Int) { Media(idMal: $idMal, type: ANIME) { description(asHtml: false) } }'
            async with sess.post('https://graphql.anilist.co',
                                 json={'query': query, 'variables': {'idMal': int(mal_id)}}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    desc = data.get('data', {}).get('Media', {}).get('description')
                    if desc:
                        return _clean_description(desc)
    except Exception:
        pass

    # 4. MAL
    if Config.MAL_CLIENT_ID:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as sess:
                async with sess.get(
                    f"https://api.myanimelist.net/v2/anime/{mal_id}",
                    params={"fields": "synopsis"},
                    headers={"X-MAL-CLIENT-ID": Config.MAL_CLIENT_ID}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('synopsis'):
                            return _clean_description(data['synopsis'])
        except Exception:
            pass

    return None


async def _fetch_english_episodes(mal_id: str) -> list:
    """Fetch original English episode data for a MAL ID from TVDB."""
    from app.utils.anime_mapping import load_mapping, get_ids_from_mal_id
    from config import Config
    load_mapping()
    ids = get_ids_from_mal_id(mal_id)
    
    if not (Config.TVDB_API_KEY and ids.get('tvdb_id')):
        return []
    
    from app.api.tvdb import get_series_episodes
    tvdb_season = int(ids['tvdb_season']) if ids.get('tvdb_season') else 1
    episodes = await get_series_episodes(ids['tvdb_id'], season_number=tvdb_season, lang='eng')
    
    # Map to video IDs matching the cache format
    result = []
    for ep in episodes:
        ep_num = ep.get('number') or ep.get('absoluteNumber')
        if ep_num:
            result.append({
                'id': f"mal:{mal_id}:{ep_num}",
                'title': ep.get('name'),
                'overview': ep.get('overview'),
            })
    return result


async def _cleanup():
    """Close persistent sessions to avoid 'Unclosed client session' warnings."""
    from app.db import _turso_client
    if _turso_client and not _turso_client.closed:
        await _turso_client.close()
    from app.api.tvdb import _session as tvdb_session
    if tvdb_session and not tvdb_session.closed:
        await tvdb_session.close()


if __name__ == "__main__":
    import sys

    async def _run():
        try:
            if len(sys.argv) > 1:
                target_mal = sys.argv[1]
                force = '--force' in sys.argv
                await translate_single(target_mal, force=force)
            else:
                await main()
        finally:
            await _cleanup()

    asyncio.run(_run())
