from functools import lru_cache
from urllib.parse import unquote
import requests
import time
from flask import Blueprint, abort
from jikanpy import Jikan
from jikanpy.exceptions import APIException

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

jikan_client = Jikan()

# Rate limiting for Jikan (3 req/sec, 60 req/min)
_jikan_last_request = 0
_jikan_request_interval = 0.35  # 350ms between requests (slightly under 3/sec)


@lru_cache(maxsize=100)
def _cached_jikan_anime(mal_id: int, extension: str = None):
    """Cached wrapper for Jikan API calls with rate limiting."""
    global _jikan_last_request
    
    # Rate limiting
    now = time.time()
    time_since_last = now - _jikan_last_request
    if time_since_last < _jikan_request_interval:
        time.sleep(_jikan_request_interval - time_since_last)
    
    _jikan_last_request = time.time()
    
    if extension:
        return jikan_client.anime(mal_id, extension=extension)
    return jikan_client.anime(mal_id)


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

    except requests.HTTPError as e:
        log_error(f"Kitsu error: {e}. Falling back to Jikan.")
        if mal_id:
            try:
                jikan_main_resp = _cached_jikan_anime(int(mal_id))
                jikan_episodes_resp = _cached_jikan_anime(int(mal_id), extension='episodes')

                meta = jikan_to_meta(jikan_main_resp, jikan_episodes_resp, meta_id, mal_id)
            except APIException as jikan_e:
                log_error(f"Jikan error: {jikan_e}")
                return respond_with({'meta': {}, 'message': str(jikan_e)}), getattr(jikan_e, 'status_code', 500)
            except Exception as general_e:
                log_error(f"Unexpected Jikan error: {general_e}")
                return respond_with({'meta': {}, 'message': 'An unexpected error occurred.'}), 500
        else:
            return respond_with({'meta': {}, 'message': str(e)}), e.response.status_code

    meta['type'] = meta_type

    if 'videos' in meta and meta['videos']:
        kitsu_id = meta.get('kitsu_id')
        for item in meta['videos']:
            if kitsu_id and 'kitsu:' in item.get("id", ""):
                item["id"] = item["id"].replace(f"kitsu:{kitsu_id}", f"{MAL_ID_PREFIX}:{mal_id}")

    return respond_with({'meta': meta}, 86400, 86400)


def jikan_to_meta(jikan_main_data: dict, jikan_episodes_data: dict, meta_id: str, mal_id: str) -> dict:
    """
    Converts Jikan API responses into a Stremio meta object format, including episodes.
    :param jikan_main_data: The main anime data from the Jikan API.
    :param jikan_episodes_data: The episode data from the Jikan API.
    :param meta_id: The Stremio meta ID for the item.
    :param mal_id: The MyAnimeList ID for the item.
    :return: A dictionary formatted as a Stremio meta object.
    """
    data = jikan_main_data.get('data', {})

    name = data.get('title_english') or data.get('title')
    description = data.get('synopsis')
    year = data.get('year')
    imdb_rating = data.get('score')

    images = data.get('images', {}).get('jpg', {})
    poster = images.get('large_image_url') or images.get('image_url')

    genres = [genre['name'] for genre in data.get('genres', [])]

    release_info = str(year) if year else None
    runtime = data.get('duration')

    trailers = []
    if data.get('trailer') and data['trailer'].get('youtube_id'):
        trailers.append({'source': data['trailer']['youtube_id'], 'type': 'Trailer'})

    videos = []
    episodes_data = jikan_episodes_data.get('data', [])
    for episode in episodes_data:
        episode_number = episode.get('mal_id')
        videos.append({
            "id": f"mal:{mal_id}:{episode_number}",
            "title": episode.get('title'),
            "episode": episode_number,
            "season": 1,
            "released": episode.get('aired'),
            "overview": None,
            "thumbnail": None,
        })

    return {
        'id': meta_id,
        'name': name,
        'description': description,
        'poster': poster,
        'background': poster,
        'genres': genres,
        'releaseInfo': release_info,
        'year': year,
        'imdbRating': imdb_rating,
        'runtime': runtime,
        'trailers': trailers,
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
