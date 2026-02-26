from flask import Blueprint, abort

from app.utils.stream_utils import respond_with
from version import __version__

manifest_blueprint = Blueprint('manifest', __name__)

genres = ['Action', 'Adventure', 'Avant Garde',
          'Award Winning', 'Boys Love', 'Comedy',
          'Drama', 'Fantasy', 'Girls Love', 'Gourmet',
          'Horror', 'Mystery', 'Romance', 'Sci-Fi',
          'Slice of Life', 'Sports', 'Supernatural',
          'Ecchi']

MANIFEST = {
    'id': 'com.skoruppa.docchi-stremio-addon',
    'version': __version__,
    'name': 'Docchi.pl Addon',
    'logo': 'https://stremio.docci.pl/static/logo.png',
    'description': 'Provides users with possibility to watch anime with polish subtitles based on data returned by Docchi.pl',
    'types': ['anime', 'series', 'movie'],
    'contactEmail': 'skoruppa@gmail.com',
    'catalogs': [
        {'type': 'anime', 'id': 'newest', 'name': 'Docchi.pl - Najnowsze Odcinki',
         'extra': [{'name': 'genre', 'options': genres}],
         'genre': genres},
        {'type': 'anime', 'id': 'latest', 'name': 'Docchi.pl - Ostatnio Dodane',
         'extra': [{'name': 'genre', 'options': genres}],
         'genre': genres},
        {'type': 'anime', 'id': 'season', 'name': 'Docchi.pl - Aktualny Sezon',
         'extra': [{'name': 'genre', 'options': genres}],
         'genre': genres},
        {'type': 'anime', 'id': 'trending', 'name': 'Docchi.pl - Popularne',
         'extra': [{'name': 'genre', 'options': genres}],
         'genre': genres},
        {
            'type': 'anime',
            'id': 'search_list',
            'name': 'Docchi.pl - Szukaj',
            'extra': [
                {'name': 'search', 'isRequired': True},
                {'name': 'genre', 'options': genres, 'isRequired': False}
            ],
            'genre': genres
        }
    ],

    'behaviorHints': {'configurable': False},
    'resources': ['catalog', 'meta', 'stream'],
    'idPrefixes': ['mal', 'kitsu'],
    "stremioAddonsConfig": {
        "issuer": "https://stremio-addons.net",
        "signature": "eyJhbGciOiJkaXIiLCJlbmMiOiJBMTI4Q0JDLUhTMjU2In0.._T2DcWi9u658Np-4PJmH3A.TQRRcCrhHuY4NCyyfK_RhV8htIVzS4mA-NlAply7ix1E81487ORg113u6gpAJa4181kQNIBoem_vyh42ox9CKBaKG1OePGzkKdBtrntEywVtFn3gjKU6FpWyNXs3obuB.YzRd5NZjmqb3FQlAgpSS9g"
      }
}

MANIFEST_VIP = {
    **MANIFEST,
    'id': 'com.skoruppa.docchi-stremio-addon-vip',
    'name': 'Docchi.pl Addon VIP',
    'idPrefixes': ['mal', 'kitsu', 'tt']
}


@manifest_blueprint.route('/manifest.json')
def addon_manifest():
    """
    Provides the manifest for the addon
    :return: JSON response
    """
    from flask import request
    from config import Config
    
    is_vip = Config.VIP_PATH in request.path
    manifest = MANIFEST_VIP if is_vip else MANIFEST
    return respond_with(manifest, 7200)
