"""TheTVDB API v4 client for fetching series metadata and episodes in Polish."""
import logging
import time
import aiohttp
from config import Config
from app.utils.common_utils import get_fanart_images

BASE_URL = "https://api4.thetvdb.com/v4"
TIMEOUT = aiohttp.ClientTimeout(total=10)

_token: str | None = None
_token_expires: float = 0


async def _get_token() -> str | None:
    """Authenticate with TVDB API and return bearer token (cached for 25 days)."""
    global _token, _token_expires
    if _token and time.time() < _token_expires:
        return _token

    if not Config.TVDB_API_KEY:
        return None

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(f"{BASE_URL}/login", json={"apikey": Config.TVDB_API_KEY}) as resp:
                if resp.status != 200:
                    logging.error(f"TVDB login failed: {resp.status}")
                    return None
                data = await resp.json()
                _token = data.get("data", {}).get("token")
                _token_expires = time.time() + 86400 * 25  # 25 days
                return _token
    except Exception as e:
        logging.error(f"TVDB login error: {e}")
        return None


async def _api_get(path: str, params: dict = None) -> dict | None:
    """Make authenticated GET request to TVDB API."""
    token = await _get_token()
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{BASE_URL}{path}", headers=headers, params=params) as resp:
                if resp.status == 401:
                    # Token expired, reset and retry once
                    global _token_expires
                    _token_expires = 0
                    token = await _get_token()
                    if not token:
                        return None
                    headers = {"Authorization": f"Bearer {token}"}
                    async with session.get(f"{BASE_URL}{path}", headers=headers, params=params) as retry_resp:
                        if retry_resp.status != 200:
                            return None
                        return await retry_resp.json()
                if resp.status != 200:
                    return None
                return await resp.json()
    except Exception as e:
        logging.error(f"TVDB API error ({path}): {e}")
        return None


async def get_series_translation(tvdb_id: int, lang: str = "pol") -> dict | None:
    """Get series translation (name + overview) for a given language."""
    data = await _api_get(f"/series/{tvdb_id}/translations/{lang}")
    if data and data.get("data"):
        return data["data"]
    return None


async def get_series_extended(tvdb_id: int) -> dict | None:
    """Get series extended record (seasons, genres, artworks, etc.)."""
    data = await _api_get(f"/series/{tvdb_id}/extended", params={"short": "true"})
    if data and data.get("data"):
        return data["data"]
    return None


async def get_series_episodes(tvdb_id: int, season_number: int = None, lang: str = "pol") -> list:
    """Fetch episodes for a series with translations in the given language.
    
    Uses /series/{id}/episodes/default/{lang} endpoint.
    If season_number is provided, filters to only that season.
    Falls back to English data + AI translation for missing Polish translations.
    Returns list of episode dicts.
    """
    episodes = await _fetch_episodes_for_lang(tvdb_id, season_number, lang)
    
    # Fallback to English if no episodes found in requested language
    if not episodes and lang != "eng":
        episodes = await _fetch_episodes_for_lang(tvdb_id, season_number, "eng")

    # If we got episodes but some lack translations, enrich from English + AI
    if episodes and lang != "eng":
        translation_complete = await _translate_missing_episode_fields(episodes, tvdb_id, season_number)
        # Mark episodes with translation status
        if not translation_complete:
            for ep in episodes:
                ep["_untranslated"] = True

    return episodes


async def _translate_missing_episode_fields(episodes: list, tvdb_id: int, season_number: int = None) -> bool:
    """For episodes missing Polish name/overview, fetch English and translate via AI.
    
    Returns True if all translations succeeded (or nothing needed), False if any failed.
    """
    from app.utils.translate import translate_to_polish
    import asyncio

    # Find episodes missing name or overview
    missing_overview = [ep for ep in episodes if not ep.get("overview") and ep.get("number", 0) > 0]
    if not missing_overview:
        return True

    # Fetch English episodes to get source text
    eng_episodes = await _fetch_episodes_for_lang(tvdb_id, season_number, "eng")
    if not eng_episodes:
        return False

    eng_map = {ep.get("number"): ep for ep in eng_episodes if ep.get("number")}

    # Collect texts to translate
    to_translate = []
    ep_indices = []
    for ep in missing_overview:
        eng_ep = eng_map.get(ep.get("number"))
        if eng_ep and eng_ep.get("overview"):
            to_translate.append(eng_ep["overview"])
            ep_indices.append(ep)
            # Also fill name from English if missing
            if not ep.get("name") and eng_ep.get("name"):
                ep["name"] = eng_ep["name"]

    if not to_translate:
        return True

    # Batch translate overviews (limit to avoid excessive API calls)
    all_succeeded = True
    translations = await asyncio.gather(
        *[translate_to_polish(t) for t in to_translate[:30]]  # cap at 30 per request
    )
    for ep, eng_text, translated in zip(ep_indices[:30], to_translate[:30], translations):
        if translated:
            ep["overview"] = translated
        else:
            # Use English fallback
            ep["overview"] = eng_text
            all_succeeded = False

    return all_succeeded


async def _fetch_episodes_for_lang(tvdb_id: int, season_number: int = None, lang: str = "pol") -> list:
    """Internal: fetch episodes for a specific language."""
    all_episodes = []
    page = 0

    while True:
        path = f"/series/{tvdb_id}/episodes/default/{lang}"
        params = {"page": page}
        if season_number is not None:
            params["season"] = season_number

        data = await _api_get(path, params=params)
        if not data:
            break

        episodes = data.get("data", {}).get("episodes", [])
        if not episodes:
            break

        all_episodes.extend(episodes)

        # Check pagination
        links = data.get("links", {})
        if links.get("next"):
            page += 1
        else:
            break

    return all_episodes


async def get_anime_meta(tvdb_id: int, mal_id: str = None, season_number: int = None,
                         imdb_id: str = None, tmdb_id: int = None) -> dict | None:
    """Fetch anime metadata from TVDB for a specific season and return Stremio-compatible meta dict.
    
    Args:
        tvdb_id: TheTVDB series ID
        mal_id: MAL ID for the content (used in video IDs)
        season_number: TVDB season number to fetch episodes for
        imdb_id: IMDB ID for fanart lookup
        tmdb_id: TMDB ID for fanart lookup
        
    Returns:
        Stremio meta dict or None
    """
    if not Config.TVDB_API_KEY:
        return None

    # Fetch series extended info and Polish translation in parallel
    import asyncio
    series_ext_task = get_series_extended(tvdb_id)
    translation_task = get_series_translation(tvdb_id, "pol")
    episodes_task = get_series_episodes(tvdb_id, season_number=season_number, lang="pol")

    series_ext, translation, episodes = await asyncio.gather(
        series_ext_task, translation_task, episodes_task
    )

    if not series_ext:
        return None

    # Series name: prefer Polish translation, fallback to original
    name = series_ext.get("name", "")
    description = None
    if translation:
        name = translation.get("name") or name
        description = translation.get("overview")

    # If no Polish description, try AI translation from English
    _description_untranslated = False
    if not description:
        eng_translation = await get_series_translation(tvdb_id, "eng")
        if eng_translation and eng_translation.get("overview"):
            from app.utils.translate import translate_to_polish
            description = await translate_to_polish(eng_translation["overview"])
            # Fallback to raw English if translation fails
            if not description:
                description = eng_translation["overview"]
                _description_untranslated = True

    # Genres
    genres = [g.get("name") for g in series_ext.get("genres", []) if g.get("name")]

    # Status
    status_obj = series_ext.get("status", {})
    status_name = status_obj.get("name") if status_obj else None
    status_map = {"Continuing": "Continuing", "Ended": "Ended", "Upcoming": "Upcoming"}
    status = status_map.get(status_name, status_name)

    # Year / releaseInfo
    first_aired = series_ext.get("firstAired", "")
    last_aired = series_ext.get("lastAired", "")
    year = first_aired[:4] if first_aired else None
    release_info = None
    if year:
        end_year = last_aired[:4] if last_aired else None
        if end_year and end_year != year:
            release_info = f"{year}-{end_year}"
        elif status == "Continuing":
            release_info = f"{year}-"
        else:
            release_info = year

    # Artwork
    poster = series_ext.get("image")
    background = None
    runtime = series_ext.get("averageRuntime")

    # Fanart
    fanart = await get_fanart_images(imdb_id=imdb_id, tvdb_id=tvdb_id, tmdb_id=tmdb_id)
    logo = fanart.get("logo")
    background = fanart.get("background") or background
    if not poster:
        poster = fanart.get("poster") or poster

    # Content type
    content_type = "series"

    # Build videos from episodes
    videos = _build_videos_from_episodes(episodes, mal_id, season_number)

    result = {
        "id": f"mal:{mal_id}" if mal_id else f"tvdb:{tvdb_id}",
        "type": content_type,
        "name": name,
        "genres": genres,
        "description": description,
        "year": year,
        "releaseInfo": release_info,
        "runtime": f"{runtime} min" if isinstance(runtime, int) else None,
        "status": status,
        "poster": poster,
        "background": background,
        "logo": logo,
        "videos": videos,
        "trailers": [],
        "links": [],
    }
    if _description_untranslated:
        result["_untranslated"] = True
    return result


def _build_videos_from_episodes(episodes: list, mal_id: str = None, season_number: int = None) -> list:
    """Build Stremio video objects from TVDB episode data.
    
    Episodes are numbered sequentially within the season (1, 2, 3, ...).
    """
    if not episodes:
        return []

    # Filter episodes by season if needed (API should already do this, but be safe)
    if season_number is not None:
        episodes = [ep for ep in episodes if ep.get("seasonNumber") == season_number]

    # Sort by episode number
    episodes.sort(key=lambda e: e.get("number", 0))

    videos = []
    for ep in episodes:
        ep_num = ep.get("number", 0)
        if ep_num <= 0:
            continue

        aired = ep.get("aired")
        released = f"{aired}T00:00:00Z" if aired else None

        title = ep.get("name") or f"Episode {ep_num}"
        overview = ep.get("overview")
        thumbnail = ep.get("image")
        if thumbnail and not thumbnail.startswith("http"):
            thumbnail = f"https://artworks.thetvdb.com{thumbnail}"

        vid_id = f"mal:{mal_id}:{ep_num}" if mal_id else f"tvdb:{ep_num}"

        videos.append({
            "id": vid_id,
            "title": title,
            "released": released,
            "season": 1,
            "episode": ep_num,
            "thumbnail": thumbnail,
            "overview": overview,
        })

    return videos
