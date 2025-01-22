from flask import Blueprint, abort

from . import MAL_ID_PREFIX
from .utils import respond_with

manifest_blueprint = Blueprint('manifest', __name__)

genres = ['Action', 'Adventure', 'Avant Garde',
          'Award Winning', 'Boys Love', 'Comedy',
          'Drama', 'Fantasy', 'Girls Love', 'Gourmet',
          'Horror', 'Mystery', 'Romance', 'Sci-Fi',
          'Slice of Life', 'Sports', 'Supernatural',
          'Ecchi']

MANIFEST = {
    'id': 'com.skoruppa.docchi-stremio-addon',
    'version': '0.0.2',
    'name': 'Docchi.pl Addon',
    'logo': 'https://docchi.pl/static/img/logo.svg',
    'description': 'Provides users with possibility to watch anime with polish subtitles based on data returned by Docchi.pl',
    'types': ['anime', 'series', 'movie'],

    'catalogs': [
        {'type': 'anime', 'id': 'winter_2025', 'name': 'Winter 2025',
         'extra': [{'name': 'genre', 'options': genres}],
         'genre': genres},
        {'type': 'anime', 'id': 'latest', 'name': 'Latest',
         'extra': [{'name': 'genre', 'options': genres}],
         'genre': genres},
        {'type': 'anime', 'id': 'trending', 'name': 'Trending',
         'extra': [{'name': 'genre', 'options': genres}],
         'genre': genres},
        {
            'type': 'anime',
            'id': 'search_list',
            'name': 'search',
            'extra': [
                {'name': 'search', 'isRequired': True},
                {'name': 'genre', 'options': genres, 'isRequired': False}
            ],
            'genre': genres
        }
    ],

    'behaviorHints': {'configurable': False},
    'resources': ['catalog', 'meta', 'stream'],
    'idPrefixes': [MAL_ID_PREFIX, 'kitsu']
}


@manifest_blueprint.route('/manifest.json')
def addon_manifest():
    """
    Provides the manifest for the addon after the user has authenticated with MyAnimeList
    :return: JSON response
    """
    return respond_with(MANIFEST)
