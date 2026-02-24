import asyncio
from datetime import timedelta
from pyMALv2.auth import Authorization
from pyMALv2.services.anime_service.anime_service import AnimeService
from config import Config
from app.utils.common_utils import get_fanart_images
from app.utils.anime_mapping import get_slug_from_mal_id, get_ids_from_mal_id
from app.routes import docchi_client

MAL_FIELDS = (
    'id,title,main_picture,alternative_titles,start_date,end_date,synopsis,mean,'
    'media_type,status,genres,num_episodes,start_season,average_episode_duration,'
    'pictures,background,related_anime,studios,statistics'
)


async def get_anime_meta(mal_id: str) -> dict | None:
    """Fetch anime metadata from MAL API and return Stremio meta dict."""
    try:
        auth = Authorization()
        auth.client_id = Config.MAL_CLIENT_ID
        anime_service = AnimeService(auth)
        mal_anime = await asyncio.to_thread(anime_service.get, int(mal_id), fields=MAL_FIELDS)
    except Exception:
        return None

    if not mal_anime:
        return None

    name = mal_anime.title
    if mal_anime.alternative_titles and mal_anime.alternative_titles.en:
        name = mal_anime.alternative_titles.en

    poster = None
    background = None
    if mal_anime.main_picture:
        poster = mal_anime.main_picture.large or mal_anime.main_picture.medium
    # background = poster

    ids = get_ids_from_mal_id(mal_id)
    fanart = await get_fanart_images(**{k: v for k, v in ids.items() if k != 'kitsu_id'})
    logo = fanart.get('logo')
    background = fanart.get('background') or background
    if not poster:
        poster = fanart.get('poster') or poster
    year = None
    release_info = None
    if mal_anime.start_date:
        try:
            year = mal_anime.start_date.year
            end_year = mal_anime.end_date.year if mal_anime.end_date else None
            if end_year and end_year != year:
                release_info = f"{year}-{end_year}"
            elif mal_anime.status == 'currently_airing':
                release_info = f"{year}-"
            else:
                release_info = str(year)
        except (ValueError, AttributeError):
            pass

    genres = [g.name for g in mal_anime.genres] if mal_anime.genres else []
    imdb_rating = mal_anime.mean or None
    status_map = {'finished_airing': 'Ended', 'currently_airing': 'Continuing', 'not_yet_aired': 'Upcoming'}
    status = status_map.get(mal_anime.status) if mal_anime.status else None
    content_type = 'movie' if mal_anime.media_type == 'movie' else 'series'
    runtime = f"{mal_anime.average_episode_duration // 60} min" if mal_anime.average_episode_duration else None

    slug = await get_slug_from_mal_id(mal_id)
    links = []
    if slug:
        links.append({'name': str(imdb_rating) if imdb_rating else 'Docchi', 'category': 'imdb',
                      'url': f"https://docchi.pl/production/as/{slug}"})
    if mal_anime.studios:
        for studio in mal_anime.studios:
            links.append({'name': studio.name, 'category': 'Studios',
                          'url': f"https://myanimelist.net/anime/producer/{studio.id}"})
    if mal_anime.related_anime:
        for related in mal_anime.related_anime:
            rel_type = related.relation_type_formatted or related.relation_type
            links.append({'name': f"{rel_type}: {related.anime.title}", 'category': 'Franchise',
                          'url': f"stremio:///detail/{content_type}/mal:{related.anime.id}"})

    num_episodes = mal_anime.num_episodes
    if not num_episodes and slug:
        try:
            episode_data = await docchi_client.get_available_episodes(slug)
            num_episodes = len(episode_data) if isinstance(episode_data, list) else 0
        except Exception:
            pass

    videos = []
    if num_episodes:
        start = mal_anime.start_date
        for ep_num in range(1, num_episodes + 1):
            episode_date = None
            if start:
                try:
                    episode_date = (start + timedelta(days=(ep_num - 1) * 7)).strftime('%Y-%m-%dT00:00:00Z')
                except Exception:
                    pass
            videos.append({
                "id": f"mal:{mal_id}:{ep_num}",
                "title": f"Episode {ep_num}",
                "episode": ep_num,
                "season": 1,
                "released": episode_date,
            })

    return {
        'id': f"mal:{mal_id}",
        'type': content_type,
        'name': name,
        'genres': genres,
        'description': mal_anime.synopsis or None,
        'year': year,
        'releaseInfo': release_info,
        'runtime': runtime,
        'status': status,
        'imdbRating': str(imdb_rating) if imdb_rating else None,
        'poster': poster,
        'background': background,
        'logo': logo,
        'videos': videos,
        'trailers': [],
        'links': links,
    }
