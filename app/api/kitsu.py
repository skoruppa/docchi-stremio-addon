import re
import aiohttp
from datetime import datetime, timedelta
from app.utils.common_utils import get_fanart_images
from app.utils.anime_mapping import get_mal_id_from_kitsu_id, get_slug_from_mal_id

BASE_URL = "https://kitsu.io/api/edge"
TIMEOUT = aiohttp.ClientTimeout(total=5)
INCLUDES = "genres,episodes,mediaRelationships.destination"


async def get_anime_meta(kitsu_id: str, mal_id: str = None, imdb_id: str = None, tvdb_id: int = None, tmdb_id: int = None) -> dict | None:
    """Fetch full anime metadata from Kitsu API and return in kitsu_to_meta-compatible format."""
    url = f"{BASE_URL}/anime/{kitsu_id}"
    params = {"include": INCLUDES}
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                return None
            raw = await resp.json()

    data = raw.get("data", {})
    included = raw.get("included", [])
    if not data:
        return None

    attrs = data.get("attributes", {})
    rels = data.get("relationships", {})

    # Build included lookup by type+id
    included_map = {(item["type"], item["id"]): item for item in included}

    # Genres
    genre_ids = [r["id"] for r in rels.get("genres", {}).get("data", [])]
    genres = [
        included_map[("genres", gid)]["attributes"]["name"]
        for gid in genre_ids
        if ("genres", gid) in included_map
    ]

    # Episodes
    episode_ids = [r["id"] for r in rels.get("episodes", {}).get("data", [])]
    episodes = [
        included_map[("episodes", eid)]
        for eid in episode_ids
        if ("episodes", eid) in included_map
    ]
    episodes.sort(key=lambda e: e["attributes"].get("number") or 0)

    subtype = attrs.get("subtype", "")
    content_type = "movie" if subtype == "movie" else "series"
    episode_count = attrs.get("episodeCount") or 0

    videos = _build_videos(kitsu_id, subtype, episodes, episode_count, attrs.get("startDate"), mal_id)

    # releaseInfo
    start = attrs.get("startDate", "") or ""
    end = attrs.get("endDate", "") or ""
    release_info = None
    if start:
        year = start[:4]
        if end and not end.startswith(year):
            release_info = f"{year}-{end[:4]}"
        elif attrs.get("status") == "current":
            release_info = f"{year}-"
        else:
            release_info = year

    # Franchise links - resolve kitsu dest IDs to mal IDs immediately
    rel_data = rels.get("mediaRelationships", {}).get("data", [])
    franchise_links = []
    allowed = {"prequel", "sequel"}
    for r in rel_data:
        item = included_map.get(("mediaRelationships", r["id"]))
        if not item:
            continue
        role = item["attributes"].get("role", "")
        if role not in allowed:
            continue
        dest_ref = item.get("relationships", {}).get("destination", {}).get("data", {})
        dest = included_map.get((dest_ref.get("type"), dest_ref.get("id")))
        if not dest:
            continue
        dest_attrs = dest.get("attributes", {})
        dest_kitsu_id = dest.get("id")
        title = dest_attrs.get("canonicalTitle", dest_kitsu_id)
        dest_mal_id = get_mal_id_from_kitsu_id(dest_kitsu_id)
        dest_id = f"mal:{dest_mal_id}" if dest_mal_id else f"kitsu:{dest_kitsu_id}"
        franchise_links.append({
            "name": f"{role.capitalize()}: {title}",
            "category": "Franchise",
            "url": f"stremio:///detail/{content_type}/{dest_id}"
        })

    # Rating/docchi link
    avg = attrs.get("averageRating")
    rating_val = round(float(avg) / 10, 1) if avg else None
    links = []
    if rating_val:
        slug = await get_slug_from_mal_id(mal_id) if mal_id else None
        links.append({
            "name": str(rating_val),
            "category": "imdb",
            "url": f"https://docchi.pl/production/as/{slug}" if slug else f"https://kitsu.io/anime/{attrs.get('slug', kitsu_id)}"
        })
    links.extend(franchise_links)

    poster_img = attrs.get("posterImage") or {}
    cover_img = attrs.get("coverImage") or {}
    ep_length = attrs.get("episodeLength")
    youtube_id = attrs.get("youtubeVideoId")

    # Titles / aliases
    titles_obj = attrs.get("titles", {})
    canonical = attrs.get("canonicalTitle", "")
    aliases = list({
        t for t in [
            titles_obj.get("en_us"),
            titles_obj.get("en"),
            titles_obj.get("en_jp"),
        ] + (attrs.get("abbreviatedTitles") or [])
        if t and t.lower() != canonical.lower()
    })

    poster = poster_img.get("medium") or poster_img.get("large")
    background = cover_img.get("original")
    logo = None

    fanart = await get_fanart_images(imdb_id=imdb_id, tvdb_id=tvdb_id, tmdb_id=tmdb_id)
    logo = fanart.get("logo")
    background = fanart.get("background") or background
    poster = fanart.get("poster") or poster

    return {
        "id": f"mal:{mal_id}" if mal_id else f"kitsu:{kitsu_id}",
        "type": content_type,
        "name": canonical,
        "aliases": aliases,
        "genres": genres,
        "description": _clean_desc(attrs.get("synopsis")),
        "year": release_info[:4] if release_info else None,
        "releaseInfo": release_info,
        "runtime": f"{ep_length} min" if isinstance(ep_length, int) else None,
        "imdbRating": str(rating_val) if rating_val else None,
        "poster": poster,
        "background": background,
        "logo": logo,
        "videos": videos,
        "trailers": [{"source": youtube_id, "type": "Trailer"}] if youtube_id else [],
        "links": links,
    }


def _build_videos(kitsu_id: str, subtype: str, episodes: list, episode_count: int, start_date: str | None, mal_id: str = None) -> list:
    if subtype == "movie" and not episodes and episode_count <= 1:
        return []

    if episodes:
        try:
            series_start = datetime.fromisoformat(start_date) if start_date else datetime(1970, 1, 1)
        except ValueError:
            series_start = datetime(1970, 1, 1)
        last_date = series_start - timedelta(weeks=1)
        videos = []
        for ep in episodes:
            a = ep["attributes"]
            num = a.get("number") or (len(videos) + 1)
            airdate = a.get("airdate")
            if airdate:
                try:
                    ep_date = datetime.fromisoformat(airdate)
                    if ep_date > last_date:
                        last_date = ep_date
                    else:
                        last_date += timedelta(weeks=1)
                        ep_date = last_date
                except ValueError:
                    last_date += timedelta(weeks=1)
                    ep_date = last_date
            else:
                last_date += timedelta(weeks=1)
                ep_date = last_date

            titles = a.get("titles", {})
            title = (titles.get("en_us") or titles.get("en") or
                     titles.get("en_jp") or a.get("canonicalTitle") or f"Episode {num}")
            vid_id = f"mal:{mal_id}:{num}" if mal_id else (f"kitsu:{kitsu_id}" if (len(episodes) == 1 and subtype in ("movie", "special", "OVA", "ONA")) else f"kitsu:{kitsu_id}:{num}")
            videos.append({
                "id": vid_id,
                "title": title,
                "released": ep_date.isoformat() + "Z",
                "season": 1,
                "episode": num,
                "thumbnail": (a.get("thumbnail") or {}).get("original"),
                "overview": _clean_desc(a.get("synopsis")),
            })
        return videos

    if episode_count:
        try:
            start = datetime.fromisoformat(start_date) if start_date else datetime(1970, 1, 1)
        except ValueError:
            start = datetime(1970, 1, 1)
        return [
            {
                "id": f"mal:{mal_id}:{ep}" if mal_id else f"kitsu:{kitsu_id}:{ep}",
                "title": f"Episode {ep}",
                "released": (start + timedelta(weeks=ep - 1)).isoformat() + "Z",
                "season": 1,
                "episode": ep,
            }
            for ep in range(1, episode_count + 1)
        ]

    return []


def _clean_desc(text: str | None) -> str | None:
    if not text:
        return None
    return re.sub(r'\n+(?:[(\[].+[)\]\n]|Source:.*)?(?:\n+Note(.|\n)+)?$', '', text) or None
