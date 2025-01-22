from functools import lru_cache
from urllib.parse import unquote
import requests
from flask import Blueprint, abort

from . import MAL_ID_PREFIX
from config import Config
from .manifest import MANIFEST
from .utils import respond_with, log_error

meta_bp = Blueprint('meta', __name__)

kitsu_API = Config.KITSU_STREMIO_API_URL
HEADERS = {
    'User-Agent': "Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:47.0) Gecko/20100101 Firefox/47.0",
    'Content-Type': 'application/json',
    'Accept': 'application/json',
}


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

    url = f"{kitsu_API}/{meta_type}/"
    try:
        mal_id = meta_id.replace(f"{MAL_ID_PREFIX}:", '')
        url += f"mal:{mal_id}.json"

        resp = requests.get(url=url, headers=HEADERS)
        resp.raise_for_status()
    except requests.HTTPError as e:
        log_error(e)
        return respond_with({'meta': {}, 'message': str(e)}), e.response.status_code

    meta = kitsu_to_meta(resp.json(), meta_id)

    meta['type'] = meta_type
    kitsu_id = meta['kitsu_id']
    for item in meta['videos']:
        if 'kitsu:' in item.get("id"):
            item["id"] = item["id"].replace(f"kitsu:{kitsu_id}", f"{MAL_ID_PREFIX}:{mal_id}")
    return respond_with({'meta': meta})


def kitsu_to_meta(kitsu_meta: dict, meta_id: str) -> dict:
    """
    Convert kitsu item to a valid Stremio meta format
    :param kitsu_meta: The kitsu item to convert
    :return: Stremio meta format
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
    if not videos:
        released = f'{releaseInfo}-01-01T01:00:00.000'
        videos = [{'id': meta_id,
                   'title': name,
                   'released': released}]
    imdb_id = meta.get('imdb_id', None)

    return {
        'id': meta_id,
        'cacheMaxAge': 43200,
        'staleRevalidate': 43200,
        'staleError': 3600,
        'kitsu_id': kitsu_id,
        'name': name,
        'genres': genres,
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
