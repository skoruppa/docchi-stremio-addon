"""TMDB API v3 client - fallback for anime metadata when TVDB is unavailable."""
import logging
import aiohttp
from config import Config

BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p"
TIMEOUT = aiohttp.ClientTimeout(total=10)


async def _api_get(path: str, params: dict = None) -> dict | None:
    """Make GET request to TMDB API v3."""
    if not Config.TMDB_API_KEY:
        return None

    params = params or {}
    params["api_key"] = Config.TMDB_API_KEY

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}{path}", params=params) as resp:
                if resp.status != 200:
                    logging.warning(f"TMDB API {path}: status {resp.status}")
                    return None
                return await resp.json()
    except Exception as e:
        logging.error(f"TMDB API error ({path}): {e}")
        return None


async def get_anime_meta(tmdb_id: int, mal_id: str = None, imdb_id: str = None) -> dict | None:
    """Fetch anime series metadata from TMDB and return Stremio-compatible meta dict.
    
    Args:
        tmdb_id: TMDB TV series ID
        mal_id: MAL ID for content identification
        imdb_id: IMDB ID for links
    
    Returns:
        Stremio meta dict or None
    """
    import asyncio
    from app.utils.common_utils import get_fanart_images

    # Fetch Polish and English details in parallel (Polish for translations, English for fallback)
    pol_task = _api_get(f"/tv/{tmdb_id}", {"language": "pl-PL"})
    eng_task = _api_get(f"/tv/{tmdb_id}", {"language": "en-US"})
    fanart_task = get_fanart_images(imdb_id=imdb_id, tmdb_id=tmdb_id)

    pol_data, eng_data, fanart = await asyncio.gather(pol_task, eng_task, fanart_task)
    fanart = fanart or {}

    data = pol_data or eng_data
    if not data:
        return None

    eng = eng_data or {}

    # Name: prefer Polish, fallback English
    name = data.get("name") or eng.get("name") or data.get("original_name", "")

    # Description: detect if Polish is actually translated or just English copy
    description = data.get("overview") or None
    _untranslated = False
    if not description and eng.get("overview"):
        description = eng["overview"]
        _untranslated = True
    elif description and eng.get("overview") and description == eng["overview"]:
        # TMDB returned same text for both languages — it's not actually translated
        _untranslated = True

    # Poster & background
    poster = f"{IMAGE_BASE}/w500{data['poster_path']}" if data.get("poster_path") else None
    background = f"{IMAGE_BASE}/original{data['backdrop_path']}" if data.get("backdrop_path") else None

    # Fanart overrides
    if fanart.get("poster"):
        poster = fanart["poster"]
    if fanart.get("background"):
        background = fanart["background"]
    logo = fanart.get("logo")

    # Genres
    genres = [g["name"] for g in data.get("genres", []) if g.get("name")]

    # Status
    status_map = {"Returning Series": "Continuing", "Ended": "Ended", "Canceled": "Ended",
                  "In Production": "Upcoming", "Planned": "Upcoming"}
    status = status_map.get(data.get("status"), data.get("status"))

    # Year / releaseInfo
    first_aired = data.get("first_air_date", "")
    last_aired = data.get("last_air_date", "")
    year = first_aired[:4] if first_aired else None
    release_info = None
    if year:
        if status == "Continuing":
            release_info = f"{year}-"
        elif last_aired and last_aired[:4] != year:
            release_info = f"{year}-{last_aired[:4]}"
        else:
            release_info = year

    # Runtime
    runtimes = data.get("episode_run_time", [])
    runtime = runtimes[0] if runtimes else None

    # Released
    released = f"{first_aired}T00:00:00.000Z" if first_aired else None

    # Rating
    vote_avg = data.get("vote_average")
    imdb_rating = str(round(vote_avg, 1)) if vote_avg and vote_avg > 0 else None

    # Links
    links = []
    if imdb_rating and imdb_id:
        links.append({"name": imdb_rating, "category": "imdb", "url": f"https://imdb.com/title/{imdb_id}"})

    result = {
        "id": f"mal:{mal_id}" if mal_id else f"tmdb:{tmdb_id}",
        "type": "series",
        "name": name,
        "genres": genres,
        "description": description,
        "year": year,
        "releaseInfo": release_info,
        "released": released,
        "runtime": f"{runtime}min" if runtime else None,
        "imdbRating": imdb_rating,
        "status": status,
        "poster": poster,
        "background": background,
        "logo": logo,
        "videos": [],
        "trailers": [],
        "links": links,
    }
    if _untranslated:
        result["_untranslated"] = True
    return result


async def get_series_episodes(tmdb_id: int, season_number: int = 1, lang: str = "pl-PL") -> list:
    """Fetch episodes for a TMDB series season.
    
    Returns list of episode dicts compatible with Stremio video format.
    """
    data = await _api_get(f"/tv/{tmdb_id}/season/{season_number}", {"language": lang})
    if not data:
        return []
    return data.get("episodes", [])


async def get_anime_videos(tmdb_id: int, mal_id: str = None) -> list:
    """Fetch episodes from TMDB and build Stremio video objects.
    
    Fetches Polish first, fills missing from English.
    """
    import asyncio
    from datetime import datetime, timezone

    # Get series info first to know how many seasons
    series = await _api_get(f"/tv/{tmdb_id}", {"language": "pl-PL"})
    if not series:
        return []

    num_seasons = series.get("number_of_seasons", 1)
    now = datetime.now(timezone.utc)

    # Fetch all seasons (Polish + English for fallback)
    pol_tasks = [_api_get(f"/tv/{tmdb_id}/season/{s}", {"language": "pl-PL"}) for s in range(1, num_seasons + 1)]
    eng_tasks = [_api_get(f"/tv/{tmdb_id}/season/{s}", {"language": "en-US"}) for s in range(1, num_seasons + 1)]

    all_results = await asyncio.gather(*pol_tasks, *eng_tasks)
    pol_results = all_results[:num_seasons]
    eng_results = all_results[num_seasons:]

    videos = []
    for season_num, (pol_data, eng_data) in enumerate(zip(pol_results, eng_results), 1):
        episodes = (pol_data or {}).get("episodes", [])
        eng_episodes = (eng_data or {}).get("episodes", [])
        eng_map = {ep.get("episode_number"): ep for ep in eng_episodes}

        for ep in episodes:
            ep_num = ep.get("episode_number", 0)
            if ep_num <= 0:
                continue

            eng_ep = eng_map.get(ep_num, {})

            # Title: prefer Polish, fallback English
            title = ep.get("name") or eng_ep.get("name") or f"Episode {ep_num}"
            _untranslated_title = False
            # If Polish title matches English exactly (or is generic "Episode X"), it's not translated
            if eng_ep.get("name") and title == eng_ep.get("name"):
                _untranslated_title = True

            # Overview
            overview = ep.get("overview") or eng_ep.get("overview") or None
            _untranslated_overview = False
            if overview and eng_ep.get("overview") and overview == eng_ep.get("overview"):
                _untranslated_overview = True
            elif not ep.get("overview") and eng_ep.get("overview"):
                _untranslated_overview = True

            # Air date & availability
            air_date = ep.get("air_date")
            released = f"{air_date}T00:00:00Z" if air_date else None
            available = True
            if released:
                try:
                    ep_date = datetime.fromisoformat(released.replace('Z', '+00:00'))
                    available = ep_date <= now
                except (ValueError, TypeError):
                    pass
            elif not air_date:
                available = False

            # Thumbnail
            thumbnail = None
            if ep.get("still_path"):
                thumbnail = f"{IMAGE_BASE}/w300{ep['still_path']}"

            vid_id = f"mal:{mal_id}:{ep_num}" if mal_id else f"tmdb:{tmdb_id}:{ep_num}"

            video = {
                "id": vid_id,
                "title": title,
                "released": released,
                "available": available,
                "season": season_num,
                "episode": ep_num,
                "thumbnail": thumbnail,
                "overview": overview,
            }

            # Runtime
            ep_runtime = ep.get("runtime")
            if ep_runtime:
                video["runtime"] = f"{ep_runtime}min"

            if _untranslated_title:
                video["_untranslated_title"] = True
            if _untranslated_overview:
                video["_untranslated_overview"] = True
            if _untranslated_title or _untranslated_overview:
                video["_untranslated"] = True

            videos.append(video)

    return videos
