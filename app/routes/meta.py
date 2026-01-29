from functools import lru_cache
from urllib.parse import unquote
import requests
from flask import Blueprint, abort
from pyMALv2.auth import Authorization
from pyMALv2.services.anime_service.anime_service import AnimeService

from . import MAL_ID_PREFIX, kitsu_client
from config import Config
from .manifest import MANIFEST
from app.utils.stream_utils import respond_with, log_error

meta_bp = Blueprint('meta', __name__)

kitsu_API = Config.KITSU_STREMIO_API_URL
HEADERS = {
    'User-Agent': "Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:47.0) Gecko/20100101 Firefox/47.0",
    'Content-Type': 'application/json',
    'Accept': 'application/json',
}

# Initialize pyMALv2
MAL_CLIENT_ID = Config.MAL_CLIENT_ID
auth = Authorization()
auth.client_id = MAL_CLIENT_ID
anime_service = AnimeService(auth)


@meta_bp.route('/meta/<meta_type>/<meta_id>.json')
@lru_cache(maxsize=1000)
def addon_meta(meta_type: str, meta_id: str):
    """
    Provides metadata for a specific content
    :param meta_type: The type of metadata to return
    :param meta_id: The ID of the content
    :return: JSON response
    """
    meta_id = unquote(meta_id)

    if meta_type not in MANIFEST['types']:
        abort(404)

    if 'kitsu' in meta_id:
        kitsu_id = meta_id.split(":")[1]
        try:
            mal_id_from_kitsu = kitsu_client.get_mal_id_from_kitsu_id(kitsu_id)
            if not mal_id_from_kitsu:
                raise ValueError("MAL ID not found for the given Kitsu ID")
            meta_id = f'{MAL_ID_PREFIX}:{mal_id_from_kitsu}'
        except Exception as e:
            log_error(e)
            return respond_with({'meta': {}, 'message': 'Could not find MAL ID for the given Kitsu ID.'}), 404

    mal_id = None
    if '_' in meta_id:
        meta_id = meta_id.replace("_", ":")

    if MAL_ID_PREFIX in meta_id:
        mal_id = meta_id.replace(f"{MAL_ID_PREFIX}:", '')

    try:
        url = f"{kitsu_API}/{meta_type}/mal:{mal_id}.json"
        resp = requests.get(url=url, headers=HEADERS)
        resp.raise_for_status()
        meta = kitsu_to_meta(resp.json(), meta_id)

    except (requests.HTTPError, requests.ConnectionError, requests.RequestException) as e:
        log_error(f"Kitsu error: {e}. Falling back to MAL API.")
        if mal_id:
            try:
                mal_anime = anime_service.get(
                    int(mal_id),
                    fields='id,title,main_picture,alternative_titles,start_date,end_date,synopsis,mean,num_episodes,start_season,genres,media_type,studios,pictures,background,average_episode_duration'
                )
                
                if not mal_anime:
                    return respond_with({'meta': {}, 'message': 'Anime not found on MAL'}), 404
                
                meta = mal_to_meta(mal_anime, meta_id, mal_id)
            except Exception as mal_e:
                log_error(f"MAL API error: {mal_e}")
                return respond_with({'meta': {}, 'message': 'An unexpected error occurred.'}), 500
        else:
            return respond_with({'meta': {}, 'message': str(e)}), 500

    meta['type'] = meta_type

    if 'videos' in meta and meta['videos']:
        kitsu_id = meta.get('kitsu_id')
        for item in meta['videos']:
            if kitsu_id and 'kitsu:' in item.get("id", ""):
                item["id"] = item["id"].replace(f"kitsu:{kitsu_id}", f"{MAL_ID_PREFIX}:{mal_id}")

    return respond_with({'meta': meta}, 86400, 86400)


def mal_to_meta(mal_anime, meta_id: str, mal_id: str) -> dict:
    """
    Converts MAL API response into a Stremio meta object format.
    :param mal_anime: The anime data from MAL API.
    :param meta_id: The Stremio meta ID for the item.
    :param mal_id: The MyAnimeList ID for the item.
    :return: A dictionary formatted as a Stremio meta object.
    """
    # Prefer English title
    name = mal_anime.title
    if mal_anime.alternative_titles and mal_anime.alternative_titles.en:
        name = mal_anime.alternative_titles.en
    
    description = mal_anime.synopsis if mal_anime.synopsis else None
    
    # Poster and background
    poster = None
    background = None
    if mal_anime.main_picture:
        poster = mal_anime.main_picture.large or mal_anime.main_picture.medium
    if mal_anime.background:
        background = mal_anime.background
    elif poster:
        background = poster
    
    # Year
    year = None
    if mal_anime.start_date:
        try:
            year = mal_anime.start_date.year
        except (ValueError, AttributeError):
            pass
    
    # Genres
    genres = []
    if mal_anime.genres:
        genres = [genre.name for genre in mal_anime.genres]
    
    # Rating
    imdb_rating = mal_anime.mean if mal_anime.mean else None
    
    # Runtime (convert from seconds to minutes)
    runtime = None
    if mal_anime.average_episode_duration:
        runtime = f"{mal_anime.average_episode_duration // 60} min"
    
    # Episodes
    videos = []
    num_episodes = mal_anime.num_episodes
    
    # If no episodes from MAL, try Docchi API
    if not num_episodes:
        try:
            from app.api.docchi import DocchiAPI
            slug = DocchiAPI.get_slug_from_mal_id(mal_id)
            if slug:
                episode_data = DocchiAPI.get_available_episodes(slug)
                num_episodes = episode_data.get('count', 0)
                if num_episodes:
                    log_error(f"Got {num_episodes} episodes from Docchi for MAL ID {mal_id}")
        except Exception as e:
            log_error(f"Failed to get episodes from Docchi: {e}")
    
    if num_episodes:
        # Get first episode date from start_date
        first_episode_date = None
        if mal_anime.start_date:
            try:
                first_episode_date = mal_anime.start_date.strftime('%Y-%m-%d')
            except (ValueError, AttributeError):
                pass
        
        for ep_num in range(1, num_episodes + 1):
            # Extrapolate release date: first episode + 7 days per episode
            episode_date = None
            if first_episode_date and mal_anime.start_date:
                try:
                    from datetime import timedelta
                    episode_datetime = mal_anime.start_date + timedelta(days=(ep_num - 1) * 7)
                    episode_date = episode_datetime.strftime('%Y-%m-%d')
                except Exception:
                    pass
            
            videos.append({
                "id": f"mal:{mal_id}:{ep_num}",
                "title": f"Episode {ep_num}",
                "episode": ep_num,
                "season": 1,
                "released": episode_date,
                "overview": None,
                "thumbnail": None,
            })
    
    return {
        'id': meta_id,
        'name': name,
        'description': description,
        'poster': poster,
        'background': background,
        'genres': genres,
        'releaseInfo': str(year) if year else None,
        'year': year,
        'imdbRating': imdb_rating,
        'runtime': runtime,
        'trailers': [],
        'videos': videos
    }


def kitsu_to_meta(kitsu_meta: dict, meta_id: str) -> dict:
    """
    Convert kitsu item to a valid Stremio meta format.
    :param kitsu_meta: The kitsu item to convert.
    :param meta_id: The Stremio meta ID for the item.
    :return: Stremio meta format.
    """
    meta = kitsu_meta.get('meta', {})
    kitsu_id = meta.get('id', '').replace('kitsu:', '')
    name = meta.get('name', '')
    genres = meta.get('genres', [])
    logo = meta.get('logo', None)
    poster = meta.get('poster', None)
    background = meta.get('background', None)
    description = meta.get('description', None)
    releaseInfo = meta.get('releaseInfo', None)
    year = meta.get('year', None)
    imdbRating = meta.get('imdbRating', None)
    trailers = meta.get('trailers', [])
    links = meta.get('links', [])
    runtime = meta.get('runtime', None)
    videos = meta.get('videos', [])
    imdb_id = meta.get('imdb_id', None)

    return {
        'cacheMaxAge': 43200,
        'staleRevalidate': 43200,
        'staleError': 3600,

        'kitsu_id': kitsu_id,
        'name': name,
        'genres': genres,
        'id': meta_id,
        'logo': logo,
        'poster': poster,
        'background': background,
        'description': description,
        'releaseInfo': releaseInfo,
        'year': year,
        'imdbRating': imdbRating,
        'trailers': trailers,
        'links': links,
        'runtime': runtime,
        'videos': videos,
        'imdb_id': imdb_id
    }
