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


def _is_non_latin(text: str) -> bool:
    """Check if text contains mostly non-Latin characters (Japanese, Chinese, Korean, etc.)."""
    if not text:
        return True
    latin_count = sum(1 for c in text if c.isascii() and c.isalpha())
    return latin_count < len(text.replace(" ", "")) * 0.5


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


async def get_series_extended(tvdb_id: int, short: bool = True) -> dict | None:
    """Get series extended record (seasons, genres, artworks, etc.).
    
    Args:
        short: If True, returns minimal data (faster). If False, includes characters/artworks.
    """
    params = {"short": "true"} if short else {}
    data = await _api_get(f"/series/{tvdb_id}/extended", params=params)
    if data and data.get("data"):
        return data["data"]
    return None


async def get_series_episodes(tvdb_id: int, season_number: int = None, lang: str = "pol") -> list:
    """Fetch episodes for a series with translations in the given language.
    
    Uses /series/{id}/episodes/default/{lang} endpoint.
    If season_number is provided, filters to only that season.
    Falls back to English data for missing Polish fields (translation runs in background).
    Returns list of episode dicts.
    """
    episodes = await _fetch_episodes_for_lang(tvdb_id, season_number, lang)
    
    # Fallback to English if no episodes found in requested language
    if not episodes and lang != "eng":
        episodes = await _fetch_episodes_for_lang(tvdb_id, season_number, "eng")

    # If we got episodes but some lack overview, fill from English (no AI blocking)
    if episodes and lang != "eng":
        await _fill_english_fallback(episodes, tvdb_id, season_number)

    return episodes


async def _fill_english_fallback(episodes: list, tvdb_id: int, season_number: int = None):
    """Detect untranslated episodes by comparing with English. Marks as _untranslated."""
    if not episodes:
        return

    # Fetch English episodes to compare
    eng_episodes = await _fetch_episodes_for_lang(tvdb_id, season_number, "eng")
    if not eng_episodes:
        return

    eng_map = {ep.get("number"): ep for ep in eng_episodes if ep.get("number")}

    for ep in episodes:
        num = ep.get("number", 0)
        if num <= 0:
            continue
        eng_ep = eng_map.get(num, {})
        
        # If overview matches English exactly, it's not translated
        if ep.get("overview") and eng_ep.get("overview") and ep["overview"] == eng_ep["overview"]:
            ep["_untranslated"] = True
        elif not ep.get("overview") and eng_ep.get("overview"):
            ep["overview"] = eng_ep["overview"]
            ep["_untranslated"] = True
        
        # If name matches English or is missing, fill from English
        if not ep.get("name") and eng_ep.get("name"):
            ep["name"] = eng_ep["name"]
        elif ep.get("name") and eng_ep.get("name") and ep["name"] == eng_ep["name"]:
            ep["_untranslated"] = True


async def _fetch_episodes_for_lang(tvdb_id: int, season_number: int = None, lang: str = "pol") -> list:
    """Internal: fetch episodes for a specific language.
    
    Note: TVDB API v4 'season' query param may not reliably filter episodes server-side,
    so we always filter client-side by seasonNumber after fetching.
    """
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

    # Client-side season filter — TVDB API may return all episodes regardless of 'season' param
    if season_number is not None:
        all_episodes = [ep for ep in all_episodes if ep.get("seasonNumber") == season_number]

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

    # Fetch series extended info (with characters) and Polish translation in parallel
    import asyncio
    series_ext_task = get_series_extended(tvdb_id, short=False)
    translation_task = get_series_translation(tvdb_id, "pol")
    episodes_task = get_series_episodes(tvdb_id, season_number=season_number, lang="pol")

    series_ext, translation, episodes = await asyncio.gather(
        series_ext_task, translation_task, episodes_task
    )

    if not series_ext:
        return None

    # Fetch trailer, poster and rating from Kitsu in one call (per-season unique images)
    trailers = []
    poster = None
    background = None
    imdb_rating = None
    kitsu_id = None
    if mal_id:
        from app.utils.anime_mapping import get_kitsu_from_mal_id
        kitsu_id = get_kitsu_from_mal_id(mal_id)
        if kitsu_id:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                    async with session.get(f"https://kitsu.io/api/edge/anime/{kitsu_id}",
                                           params={"fields[anime]": "posterImage,coverImage,youtubeVideoId,averageRating"}) as resp:
                        if resp.status == 200:
                            kdata = (await resp.json()).get("data", {}).get("attributes", {})
                            poster = (kdata.get("posterImage") or {}).get("large") or (kdata.get("posterImage") or {}).get("medium")
                            background = (kdata.get("coverImage") or {}).get("original")
                            yt_id = kdata.get("youtubeVideoId")
                            if yt_id:
                                trailers = [{"source": yt_id, "type": "Trailer"}]
                            avg_rating = kdata.get("averageRating")
                            if avg_rating:
                                imdb_rating = str(round(float(avg_rating) / 10, 1))
            except Exception:
                pass

    # Series name: prefer Polish translation, then English, fallback to original
    name = series_ext.get("name", "")
    description = None
    if translation:
        name = translation.get("name") or name
        description = translation.get("overview")

    # If name is still non-Latin (e.g. Japanese), get English name
    eng_translation = None
    if not name or _is_non_latin(name):
        eng_translation = await get_series_translation(tvdb_id, "eng")
        if eng_translation and eng_translation.get("name"):
            name = eng_translation["name"]

    # If no Polish description, use English and mark for batch translation later
    _description_untranslated = False
    if not description:
        if not eng_translation:
            eng_translation = await get_series_translation(tvdb_id, "eng")
        if eng_translation and eng_translation.get("overview"):
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

    # Artwork - runtime from TVDB
    runtime = series_ext.get("averageRuntime")

    # Docchi fallback for poster if Kitsu failed
    if not poster and mal_id:
        try:
            from app.utils.anime_mapping import get_slug_from_mal_id
            from app.routes import docchi_client
            slug = await get_slug_from_mal_id(mal_id)
            if slug:
                details = await docchi_client.get_anime_details(slug)
                if details and details.get('cover'):
                    poster = details['cover']
        except Exception:
            pass

    # Fanart for logo, background (series-level)
    fanart = await get_fanart_images(imdb_id=imdb_id, tvdb_id=tvdb_id, tmdb_id=tmdb_id)
    logo = fanart.get("logo")
    background = fanart.get("background") or background
    # Only use fanart poster as absolute last resort (it's series-level, not season-specific)
    if not poster:
        poster = fanart.get("poster") or series_ext.get("image")

    # Cast links from TVDB characters
    cast_links = []
    characters = series_ext.get("characters") or []
    for char in characters:
        if char.get("type") == "Actor" or char.get("peopleType") == "Actor":
            person_name = char.get("personName")
            if person_name:
                cast_links.append({
                    "name": person_name,
                    "category": "Cast",
                    "url": f"stremio:///search?search={person_name.replace(' ', '%20')}"
                })
        if len(cast_links) >= 10:
            break

    # Certification from TVDB contentRatings
    certification = None
    content_ratings = series_ext.get("contentRatings") or []
    # Prefer "jpn" rating, then "usa", then first available
    for preferred_country in ["jpn", "usa"]:
        for cr in content_ratings:
            if cr.get("country") == preferred_country and cr.get("name"):
                certification = cr["name"]
                break
        if certification:
            break
    if not certification and content_ratings:
        certification = content_ratings[0].get("name")

    # Season posters from Kitsu for all seasons sharing this TVDB ID
    season_posters = []
    if mal_id:
        from app.utils.anime_mapping import get_all_seasons_for_tvdb_id
        all_seasons = get_all_seasons_for_tvdb_id(tvdb_id)
        if all_seasons and len(all_seasons) > 1:
            from app.utils.anime_mapping import get_kitsu_from_mal_id as _get_kitsu
            kitsu_ids_for_posters = []
            for season_entry in all_seasons:
                entry_mal_id = str(season_entry.get('mal_id', ''))
                entry_kitsu_id = _get_kitsu(entry_mal_id) if entry_mal_id else None
                if entry_kitsu_id:
                    kitsu_ids_for_posters.append(entry_kitsu_id)
            
            if kitsu_ids_for_posters:
                try:
                    # Batch fetch posters from Kitsu (max ~10 seasons)
                    ids_param = ",".join(kitsu_ids_for_posters[:15])
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
                        async with session.get(f"https://kitsu.io/api/edge/anime",
                                               params={"filter[id]": ids_param,
                                                       "fields[anime]": "posterImage"}) as resp:
                            if resp.status == 200:
                                kdata = (await resp.json()).get("data", [])
                                # Build map id -> poster
                                poster_map = {}
                                for item in kdata:
                                    kid = item.get("id")
                                    p_img = (item.get("attributes", {}).get("posterImage") or {})
                                    p_url = p_img.get("large") or p_img.get("medium")
                                    if kid and p_url:
                                        poster_map[kid] = p_url
                                # Ordered by season
                                for kid in kitsu_ids_for_posters:
                                    if kid in poster_map:
                                        season_posters.append(poster_map[kid])
                except Exception:
                    pass

    # Content type
    content_type = "series"

    # Build videos from episodes
    airs_time = series_ext.get("airsTime") or "00:00"
    original_country = series_ext.get("originalCountry") or ""
    videos = _build_videos_from_episodes(episodes, mal_id, season_number, airs_time, original_country, backdrop=background)

    # Released date (series premiere)
    released = f"{first_aired}T00:00:00.000Z" if first_aired else None

    # Rating link (imdb or kitsu/docchi fallback)
    rating_link = None
    if imdb_rating:
        if imdb_id:
            rating_link = {"name": imdb_rating, "category": "imdb", "url": f"https://imdb.com/title/{imdb_id}"}
        else:
            rating_link = {"name": imdb_rating, "category": "imdb", "url": f"https://kitsu.io/anime/{kitsu_id}" if kitsu_id else ""}
    
    links = []
    if rating_link:
        links.append(rating_link)
    links.extend(cast_links)

    result = {
        "id": f"mal:{mal_id}" if mal_id else f"tvdb:{tvdb_id}",
        "type": content_type,
        "name": name,
        "country": original_country or None,
        "genres": genres,
        "description": description,
        "year": year,
        "releaseInfo": release_info,
        "released": released,
        "runtime": f"{runtime}min" if isinstance(runtime, int) else None,
        "imdbRating": imdb_rating,
        "status": status,
        "certification": certification,
        "poster": poster,
        "background": background,
        "logo": logo,
        "videos": videos,
        "trailers": trailers,
        "links": links,
    }
    if season_posters:
        result["seasonPosters"] = season_posters
    if _description_untranslated:
        result["_untranslated"] = True
    return result


def _airs_time_to_utc(airs_time: str, original_country: str) -> str:
    """Convert local airs_time to UTC time string (HH:MM:SS).
    
    TVDB airsTime is local to the country of origin:
    - jpn: JST (UTC+9)
    - usa/can: EST (UTC-5)
    - kor: KST (UTC+9)
    - gbr: GMT (UTC+0)
    - Others: assume UTC
    """
    # Country -> UTC offset in hours
    OFFSETS = {
        "jpn": 9,
        "kor": 9,
        "chn": 8,
        "usa": -5,
        "can": -5,
        "gbr": 0,
        "fra": 1,
        "deu": 1,
        "aus": 10,
    }

    try:
        parts = airs_time.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return "00:00:00"

    offset = OFFSETS.get(original_country.lower(), 0)
    utc_hour = (hour - offset) % 24
    return f"{utc_hour:02d}:{minute:02d}:00"


def _build_videos_from_episodes(episodes: list, mal_id: str = None, season_number: int = None, airs_time: str = "00:00", original_country: str = "", skip_season_filter: bool = False, backdrop: str = None) -> list:
    """Build Stremio video objects from TVDB episode data.
    
    Episodes are numbered sequentially within the season (1, 2, 3, ...).
    airs_time is the series broadcast time in local timezone.
    original_country is used to determine timezone offset (jpn=UTC+9, usa=UTC-5 EST).
    skip_season_filter: if True, skip filtering by seasonNumber (already pre-filtered).
    backdrop: fallback thumbnail URL for episodes without their own image.
    """
    if not episodes:
        return []

    # Filter episodes by season if needed (API should already do this, but be safe)
    if season_number is not None and not skip_season_filter:
        episodes = [ep for ep in episodes if ep.get("seasonNumber") == season_number]

    # Sort by episode number
    episodes.sort(key=lambda e: e.get("number", 0))

    # Calculate UTC offset based on country
    utc_released = _airs_time_to_utc(airs_time, original_country)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    videos = []
    for ep in episodes:
        ep_num = ep.get("number", 0)
        if ep_num <= 0:
            continue

        aired = ep.get("aired")
        released = f"{aired}T{utc_released}Z" if aired else None

        # Determine availability based on release date
        available = True
        if released:
            try:
                ep_date = datetime.fromisoformat(released.replace('Z', '+00:00'))
                available = ep_date <= now
            except (ValueError, TypeError):
                available = True
        elif not aired:
            # No air date at all = future/unknown
            available = False

        title = ep.get("name") or f"Episode {ep_num}"
        overview = ep.get("overview")
        thumbnail = ep.get("image")
        if thumbnail and not thumbnail.startswith("http"):
            thumbnail = f"https://artworks.thetvdb.com{thumbnail}"

        vid_id = f"mal:{mal_id}:{ep_num}" if mal_id else f"tvdb:{ep_num}"

        # Episode runtime from TVDB
        ep_runtime = ep.get("runtime")
        runtime_str = f"{ep_runtime}min" if ep_runtime else None

        video = {
            "id": vid_id,
            "title": title,
            "released": released,
            "available": available,
            "season": 1,
            "episode": ep_num,
            "thumbnail": thumbnail,
            "overview": overview,
        }
        if runtime_str:
            video["runtime"] = runtime_str
        if ep.get("_untranslated"):
            video["_untranslated"] = True
        videos.append(video)

    return videos


async def _fetch_trailer_from_kitsu(kitsu_id: str) -> list:
    """Fetch YouTube trailer ID from Kitsu API."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as session:
            async with session.get(f"https://kitsu.io/api/edge/anime/{kitsu_id}",
                                   params={"fields[anime]": "youtubeVideoId"}) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                yt_id = data.get("data", {}).get("attributes", {}).get("youtubeVideoId")
                if yt_id:
                    return [{"source": yt_id, "type": "Trailer"}]
    except Exception:
        pass
    return []
