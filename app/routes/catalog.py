import urllib.parse
import asyncio
import logging

import aiohttp
from flask import Blueprint, abort, url_for, request, Request
from werkzeug.exceptions import abort

from . import docchi_client
from app.db.db import save_slug_from_mal_id, save_mal_id_from_slug, get_mal_id_from_slug
from app.utils.stream_utils import cache, respond_with, log_error
from app.utils.meta_cache import fetch_and_cache_meta
from .manifest import MANIFEST, genres as manifest_genres

catalog_bp = Blueprint('catalog', __name__)


def _get_transport_url(req: Request):
    """
    Get the transport URL for the user 'user_id'
    :param req: The request object
    :return: The transport URL
    """
    return urllib.parse.quote_plus(
        req.root_url[:-1] + url_for('manifest.addon_manifest'))


def _is_valid_catalog(catalog_type: str, catalog_id: str):
    """
    Check if the catalog type and id are valid
    :param catalog_type: The type of catalog to return
    :param catalog_id: The ID of the catalog to return, MAL divides a user's anime list into different categories
           (e.g. plan to watch, watching, completed, on hold, dropped)
    :return: True if the catalog type and id are valid, False otherwise
    """
    if catalog_type in MANIFEST['types']:
        for catalog in MANIFEST['catalogs']:
            if catalog['id'] == catalog_id or catalog_id == 'winter_2025':
                return True
    return False


async def _process_latest_anime(results):
    """
    Get only unique anime and add mal ids to them
    :param results: latest episode results
    :return: Sorted list with mal ids
    """
    if not results:
        return []
    
    unique_anime = {}
    for anime in results:
        anime_id = anime.get("anime_id") or anime.get("slug")
        if anime_id not in unique_anime:
            unique_anime[anime_id] = {
                "slug": anime_id,
                "cover": anime.get("cover"),
                "title": anime.get("title"),
                "title_en": anime.get("title_en")
            }
    unique_anime_list = list(unique_anime.values())
    for u_anime in unique_anime_list:
        exists, saved_mal_id = get_mal_id_from_slug(u_anime['slug'])
        if saved_mal_id:
            u_anime['mal_id'] = saved_mal_id
        else:
            try:
                anime_details = await docchi_client.get_anime_details(u_anime['slug'])
                u_anime['mal_id'] = anime_details['mal_id']
                save_mal_id_from_slug(u_anime['slug'], anime_details['mal_id'])
            except Exception as e:
                logging.error(f"Failed to get anime details for {u_anime['slug']}: {e}")
                continue
    return unique_anime_list


def _set_cache_time(catalog_id):
    if catalog_id == 'search_list':
        cache_time = 3600
    elif catalog_id == 'newest':
        cache_time = 60
    elif catalog_id == 'latest':
        cache_time = 60
    elif catalog_id == 'season':
        cache_time = 86400
    elif catalog_id == 'trending':
        cache_time = 86400
    else:
        cache_time = 0

    return cache_time


async def _fetch_anime_list(search, catalog_id, genre):
    """
    Fetch a list of anime from Docchi API based on the provided parameters
    :param search: The search query
    :param catalog_id: The ID of the catalog to return
    :param genre: The fields to return
    :return: The list of anime
    """
    season, season_year = docchi_client.get_current_season()

    if search:
        search = urllib.parse.unquote(search)
    if search and not genre:
        if len(search) < 3:
            return []
        return await docchi_client.search_anime(name=search)
    if genre:
        results = await docchi_client.get_anime_by_genre(genre=genre)
        if not results:
            return []
        if search:
            if len(search) < 3:
                return []
            filtered_results = list(filter(lambda x: search.lower() in x["title"].lower(), results))
            return filtered_results
        return results
    if catalog_id == 'latest':
        latest = await docchi_client.get_latest_episodes(season, season_year)
        if not latest:
            return []
        return await _process_latest_anime(latest)
    elif catalog_id == 'newest':
        recent = await docchi_client.get_recent_episodes(season, season_year)
        if not recent:
            return []
        return await _process_latest_anime(recent)
    elif catalog_id == "trending":
        trending = await docchi_client.get_trending_anime()
        if not trending:
            return []
        return await _process_latest_anime(trending)
    elif catalog_id == "season":
        return await docchi_client.get_seasonal_anime(season, season_year)
    return []


@catalog_bp.route('/catalog/<catalog_type>/<catalog_id>.json')
@catalog_bp.route('/catalog/<catalog_type>/<catalog_id>/search=<search>.json')
@catalog_bp.route('/catalog/<catalog_type>/<catalog_id>/genre=<genre>.json')
@catalog_bp.route('/catalog/<catalog_type>/<catalog_id>/genre=<genre>&search=<search>.json')
@cache.cached()
async def addon_catalog(catalog_type: str, catalog_id: str, genre: str = None,
                  search: str = None):
    """
    Provides a list of anime from MyAnimeList
    :param catalog_type: The type of catalog to return
    :param catalog_id: The ID of the catalog to return, MAL divides a user's anime list into different categories
           (e.g. plan to watch, watching, completed, on hold, dropped)
    :param genre: The genre to filter by
    :param search: Used to search globally for an anime on MyAnimeList
    :return: JSON response
    """
    if not _is_valid_catalog(catalog_type, catalog_id):
        abort(404)

    cache_time = _set_cache_time(catalog_id)

    try:
        response_data = await _fetch_anime_list(search, catalog_id, genre)

        async def _get_meta(anime_item):
            mal_id = anime_item.get('mal_id')
            if mal_id:
                try:
                    meta, _ = await fetch_and_cache_meta(f"mal:{mal_id}")
                    if meta:
                        meta['type'] = catalog_type
                        return meta
                except Exception:
                    pass
            return docchi_to_meta(anime_item, catalog_type=catalog_type, catalog_id=catalog_id, transport_url=_get_transport_url(request))

        meta_previews = await asyncio.gather(*[_get_meta(item) for item in response_data])
        return respond_with({'metas': list(meta_previews)}, cache_time, 900)
    except ValueError as e:
        return respond_with({'metas': [], 'message': str(e)}), 400
    except aiohttp.ClientError as e:
        log_error(e)
        return respond_with({'metas': []}, cache_time, 900)


def docchi_to_meta(anime_item: dict, catalog_type: str, catalog_id: str, transport_url: str):
    """
    Convert MAL anime item to a valid Stremio meta format
    :param anime_item: The Docchi anime item to convert
    :param catalog_type: The type of catalog being referenced in the link meta object
    :param catalog_id: The id of catalog being referenced in the link meta object
    :param transport_url: The url to the addon's manifest.json
    :return: Stremio meta format
    """

    formatted_content_id = None
    content_id = anime_item.get('mal_id', None)
    save_slug_from_mal_id(content_id, anime_item.get('slug', None))
    if content_id:
        formatted_content_id = f"mal:{content_id}"

    title = anime_item.get('title', None)
    poster = anime_item.get('cover', {})

    anime_item_genres = list(anime_item.get('genres', []))
    filtered_genres = list(filter(lambda y: y in manifest_genres, anime_item_genres))
    genres, links = handle_genres_and_links(filtered_genres, transport_url, catalog_type, catalog_id)

    if media_type := anime_item.get('series_type', '').lower():
        if media_type in ['ona', 'ova', 'special', 'tv', 'unknown', 'tv special']:
            media_type = 'series'
    if not media_type:
        media_type = 'series'

    return {
        'cacheMaxAge': 43200,
        'staleRevalidate': 3600,
        'staleError': 3600,
        'id': formatted_content_id,
        'name': title,
        'type': media_type,
        'genres': genres,
        'links': links,
        'poster': poster,
    }


def handle_genres_and_links(genres, transport_url, catalog_type, catalog_id):
    """
    Handle the genres and links from Docchi
    """
    if not genres:
        return [], []

    links = [{'name': genre, 'category': 'Genres',
              'url': f"stremio:///discover/{transport_url}/{catalog_type}/{catalog_id}"
                     f"?genre={genre}"}
             for genre in genres]

    return genres, links