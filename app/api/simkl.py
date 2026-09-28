"""Simkl API client for resolving anime ID mappings.

Uses /redirect (301) for cheap ID resolution, then CF-cached detail endpoints.
See https://api.simkl.org/api-reference/redirect
"""
import re
import logging
import aiohttp
from config import Config

SIMKL_URL = "https://api.simkl.com"
TIMEOUT = aiohttp.ClientTimeout(total=10)

# Common params required by every Simkl request
def _params(**extra) -> dict:
    return {"client_id": Config.SIMKL_CLIENT_ID, "app-name": "docchi-stremio", "app-version": "1.0", **extra}

HEADERS = {"User-Agent": "docchi-stremio/1.0"}


async def _resolve_simkl_id(session: aiohttp.ClientSession, **id_params) -> tuple[int | None, str | None]:
    """Resolve any external ID to (simkl_id, type) via /redirect.
    
    Returns (simkl_id, type_str) or (None, None).
    type_str is 'movies', 'tv', or 'anime'.
    """
    params = _params(to="simkl", **id_params)
    try:
        async with session.get(
            f"{SIMKL_URL}/redirect",
            params=params,
            headers=HEADERS,
            allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status not in (301, 302):
                return None, None
            location = resp.headers.get("Location", "")
            # Parse: https://simkl.com/anime/12345/slug-name
            m = re.search(r"simkl\.com/(anime|tv|movies)/(\d+)", location)
            if m:
                return int(m.group(2)), m.group(1)
    except Exception as e:
        logging.warning(f"[Simkl] /redirect failed: {e}")
    return None, None


async def get_ids_from_mal(mal_id: int) -> dict | None:
    """Resolve all external IDs for an anime by MAL ID via Simkl.

    Uses /redirect + /anime/{id} (CF-cached) instead of /search/id.
    Returns dict with tvdb_id, imdb_id, tmdb_id, tvdb_season, or None.
    """
    if not Config.SIMKL_CLIENT_ID:
        return None

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            simkl_id, _ = await _resolve_simkl_id(session, mal=mal_id)
            if not simkl_id:
                return None

            details_url = f"{SIMKL_URL}/anime/{simkl_id}"
            async with session.get(
                details_url,
                params=_params(extended="full"),
                headers=HEADERS,
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            ids = data.get("ids", {})
            tvdb_id = int(ids["tvdb"]) if ids.get("tvdb") else None
            imdb_id = ids.get("imdb")
            tmdb_id = int(ids["tmdb"]) if ids.get("tmdb") else None
            tvdb_season = data.get("season")

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
    """
    if not Config.SIMKL_CLIENT_ID:
        return None

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            simkl_id, _ = await _resolve_simkl_id(session, mal=mal_id)
            if not simkl_id:
                return None

            episodes_url = f"{SIMKL_URL}/anime/episodes/{simkl_id}"
            async with session.get(
                episodes_url,
                params=_params(),
                headers=HEADERS,
            ) as resp:
                if resp.status != 200:
                    return None
                episodes = await resp.json()

            if not episodes:
                return None

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


async def get_ids_from_mal_by_imdb(imdb_id: str) -> int | None:
    """Resolve IMDB ID to MAL ID via Simkl.
    
    Uses /redirect to get simkl_id, then /anime/{id} for MAL ID.
    Returns MAL ID (int) or None.
    """
    if not Config.SIMKL_CLIENT_ID or not imdb_id:
        return None

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            simkl_id, item_type = await _resolve_simkl_id(session, imdb=imdb_id)
            if not simkl_id:
                return None

            endpoint = "anime" if item_type == "anime" else "tv"
            details_url = f"{SIMKL_URL}/{endpoint}/{simkl_id}"
            async with session.get(
                details_url,
                params=_params(extended="full"),
                headers=HEADERS,
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            mal_id = data.get("ids", {}).get("mal")
            if mal_id:
                logging.info(f"[Simkl] Resolved imdb:{imdb_id} -> mal:{mal_id}")
                return int(mal_id)

    except Exception as e:
        logging.warning(f"[Simkl] Failed to resolve imdb:{imdb_id}: {e}")

    return None


async def get_ids_from_mal_by_tvdb(tvdb_id: int) -> int | None:
    """Resolve TVDB ID to MAL ID via Simkl.
    
    Uses /redirect to get simkl_id, then /anime/{id} for MAL ID.
    Returns MAL ID (int) or None.
    """
    if not Config.SIMKL_CLIENT_ID or not tvdb_id:
        return None

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            simkl_id, item_type = await _resolve_simkl_id(session, tvdb=tvdb_id)
            if not simkl_id:
                return None

            endpoint = "anime" if item_type == "anime" else "tv"
            details_url = f"{SIMKL_URL}/{endpoint}/{simkl_id}"
            async with session.get(
                details_url,
                params=_params(extended="full"),
                headers=HEADERS,
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            mal_id = data.get("ids", {}).get("mal")
            if mal_id:
                logging.info(f"[Simkl] Resolved tvdb:{tvdb_id} -> mal:{mal_id}")
                return int(mal_id)

    except Exception as e:
        logging.warning(f"[Simkl] Failed to resolve tvdb:{tvdb_id}: {e}")

    return None
