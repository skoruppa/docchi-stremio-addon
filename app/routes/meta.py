from urllib.parse import unquote
from flask import Blueprint, abort
from pyMALv2.auth import Authorization
from pyMALv2.services.anime_service.anime_service import AnimeService
from config import Config
from .manifest import MANIFEST
from app.utils.stream_utils import respond_with, log_error, log_warning, cache
from app.utils.meta_cache import fetch_and_cache_meta

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
@cache.cached(timeout=86400)
async def addon_meta(meta_type: str, meta_id: str):
    """
    Provides metadata for a specific content
    :param meta_type: The type of metadata to return
    :param meta_id: The ID of the content
    :return: JSON response
    """
    from flask import request
    is_vip = Config.VIP_PATH in request.path

    meta_id = unquote(meta_id)

    if meta_type not in MANIFEST['types']:
        abort(404)

    # Handle underscore format
    if '_' in meta_id:
        meta_id = meta_id.replace("_", ":")
    
    # Fetch metadata (handles mal/kitsu/imdb conversion internally)
    meta, mal_id = await fetch_and_cache_meta(meta_id, is_vip)
    
    if not meta:
        return respond_with({'meta': {}, 'message': 'Could not fetch anime metadata'}), 404
    
    # Update meta fields
    meta['id'] = meta_id
    meta['type'] = meta_type

    # Fix video IDs - use MAL ID for video IDs instead of original content_id
    if 'videos' in meta and meta['videos'] and mal_id:
        for item in meta['videos']:
            video_id = item.get("id", "")
            # Extract episode number from video_id (e.g., "kitsu:5121241:2" -> "2")
            if ':' in video_id:
                episode = video_id.split(':')[-1]
                # Use MAL ID for video (e.g., "mal:241:2")
                item["id"] = f"mal:{mal_id}:{episode}"

    return respond_with({'meta': meta}, 86400, 86400)


async def mal_to_meta(mal_anime, meta_id: str, mal_id: str) -> dict:
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
            from . import docchi_client
            slug = await docchi_client.get_slug_from_mal_id(mal_id)
            if slug:
                episode_data = await docchi_client.get_available_episodes(slug)
                num_episodes = len(episode_data) if isinstance(episode_data, list) else 0
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
