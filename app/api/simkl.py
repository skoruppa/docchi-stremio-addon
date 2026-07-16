"""Simkl API client for resolving anime ID mappings."""
import logging
import aiohttp
from config import Config

SIMKL_URL = "https://api.simkl.com"
TIMEOUT = aiohttp.ClientTimeout(total=10)


async def get_ids_from_mal(mal_id: int) -> dict | None:
    """Resolve all external IDs for an anime by MAL ID via Simkl.

    Returns dict with tvdb_id, imdb_id, tmdb_id, tvdb_season, or None if not found.
    """
    if not Config.SIMKL_CLIENT_ID:
        return None

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # Step 1: Search by MAL ID to get Simkl ID
            search_url = f"{SIMKL_URL}/search/id?mal={mal_id}&client_id={Config.SIMKL_CLIENT_ID}"
            async with session.get(search_url, headers={"User-Agent": "docchi-stremio/1.0"}) as resp:
                if resp.status != 200:
                    return None
                results = await resp.json()

            if not results:
                return None

            simkl_id = results[0].get("ids", {}).get("simkl")
            if not simkl_id:
                return None

            # Step 2: Get full details with extended IDs and season info
            details_url = f"{SIMKL_URL}/anime/{simkl_id}?extended=full&client_id={Config.SIMKL_CLIENT_ID}"
            async with session.get(details_url, headers={"User-Agent": "docchi-stremio/1.0"}) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            ids = data.get("ids", {})
            tvdb_id = int(ids["tvdb"]) if ids.get("tvdb") else None
            imdb_id = ids.get("imdb")
            tmdb_id = int(ids["tmdb"]) if ids.get("tmdb") else None
            tvdb_season = data.get("season")  # Simkl provides TVDB season number directly

            if not tvdb_id and not imdb_id and not tmdb_id:
                return None

            logging.info(
                f"[Simkl] Resolved mal:{mal_id} -> tvdb:{tvdb_id}, imdb:{imdb_id}, "
                f"tmdb:{tmdb_id}, season:{tvdb_season}"
            )

            return {
                "tvdb_id": tvdb_id,
                "imdb_id": imdb_id,
                "tmdb_id": tmdb_id,
                "tvdb_season": tvdb_season,
            }

    except Exception as e:
        logging.warning(f"[Simkl] Failed to resolve mal:{mal_id}: {e}")
        return None


async def get_episode_tvdb_mapping(mal_id: int) -> dict | None:
    """Get TVDB season/episode mapping for all episodes of an anime by MAL ID.

    Returns dict mapping absolute episode number -> {'season': int, 'episode': int},
    plus 'simkl_id' and 'total_episodes'. Returns None if not found.

    Example result:
        {
            'simkl_id': 41066,
            'total_episodes': 366,
            'mapping': {
                1: {'season': 1, 'episode': 1},
                2: {'season': 1, 'episode': 2},
                ...
                21: {'season': 2, 'episode': 1},
            }
        }
    """
    if not Config.SIMKL_CLIENT_ID:
        return None

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            # Step 1: Get Simkl ID from MAL ID
            search_url = f"{SIMKL_URL}/search/id?mal={mal_id}&client_id={Config.SIMKL_CLIENT_ID}"
            async with session.get(search_url, headers={"User-Agent": "docchi-stremio/1.0"}) as resp:
                if resp.status != 200:
                    return None
                results = await resp.json()

            if not results:
                return None

            simkl_id = results[0].get("ids", {}).get("simkl")
            if not simkl_id:
                return None

            # Step 2: Get all episodes with TVDB coordinates
            episodes_url = f"{SIMKL_URL}/anime/episodes/{simkl_id}?client_id={Config.SIMKL_CLIENT_ID}"
            async with session.get(episodes_url, headers={"User-Agent": "docchi-stremio/1.0"}) as resp:
                if resp.status != 200:
                    return None
                episodes = await resp.json()

            if not episodes:
                return None

            # Build mapping: absolute ep number -> tvdb {season, episode}
            mapping = {}
            for ep in episodes:
                ep_num = ep.get("episode")
                tvdb = ep.get("tvdb")
                if ep_num and tvdb and tvdb.get("season") and tvdb.get("episode"):
                    mapping[int(ep_num)] = {
                        "season": tvdb["season"],
                        "episode": tvdb["episode"],
                    }

            if not mapping:
                return None

            logging.info(f"[Simkl] Got episode mapping for mal:{mal_id}: {len(mapping)} episodes with TVDB coords")

            return {
                "simkl_id": simkl_id,
                "total_episodes": len(mapping),
                "mapping": mapping,
            }

    except Exception as e:
        logging.warning(f"[Simkl] Failed to get episode mapping for mal:{mal_id}: {e}")
        return None
