from flask import Blueprint, abort

from . import MAL_ID_PREFIX
from app.utils.stream_utils import respond_with

manifest_blueprint = Blueprint('manifest', __name__)

genres = ['Action', 'Adventure', 'Avant Garde',
          'Award Winning', 'Boys Love', 'Comedy',
          'Drama', 'Fantasy', 'Girls Love', 'Gourmet',
          'Horror', 'Mystery', 'Romance', 'Sci-Fi',
          'Slice of Life', 'Sports', 'Supernatural',
          'Ecchi']

MANIFEST = {
    'id': 'com.skoruppa.docchi-stremio-addon',
    'version': '0.0.5',
    'name': 'Docchi.pl Addon',
    'logo': 'https://docchi.pl/static/img/logo.svg',
    'description': 'Provides users with possibility to watch anime with polish subtitles based on data returned by Docchi.pl',
    'types': ['anime', 'series', 'movie'],
    'contactEmail': 'skoruppa@gmail.com',
    'catalogs': [
        {'type': 'anime', 'id': 'season', 'name': 'Current Season',
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
    'idPrefixes': [MAL_ID_PREFIX, 'kitsu'],
    "stremioAddonsConfig": {
        "issuer": "https://stremio-addons.net",
        "signature": "eyJhbGciOiJkaXIiLCJlbmMiOiJBMTI4Q0JDLUhTMjU2In0.._T2DcWi9u658Np-4PJmH3A.TQRRcCrhHuY4NCyyfK_RhV8htIVzS4mA-NlAply7ix1E81487ORg113u6gpAJa4181kQNIBoem_vyh42ox9CKBaKG1OePGzkKdBtrntEywVtFn3gjKU6FpWyNXs3obuB.YzRd5NZjmqb3FQlAgpSS9g"
      }
}


@manifest_blueprint.route('/manifest.json')
def addon_manifest():
    """
    Provides the manifest for the addon after the user has authenticated with MyAnimeList
    :return: JSON response
    """
    return respond_with(MANIFEST, 7200)
