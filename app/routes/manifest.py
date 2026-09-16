from fastapi import APIRouter, Request

from app.utils.stream_utils import respond_with
from version import __version__

manifest_router = APIRouter()

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

    'behaviorHints': {'configurable': True, 'configurationRequired': False},
    'resources': ['catalog', 'meta', 'stream'],
    'idPrefixes': ['mal', 'kitsu', 'tt', 'tvdb'],
    "stremioAddonsConfig": {
        "issuer": "https://stremio-addons.net",
        "signature": "eyJhbGciOiJkaXIiLCJlbmMiOiJBMTI4Q0JDLUhTMjU2In0.._T2DcWi9u658Np-4PJmH3A.TQRRcCrhHuY4NCyyfK_RhV8htIVzS4mA-NlAply7ix1E81487ORg113u6gpAJa4181kQNIBoem_vyh42ox9CKBaKG1OePGzkKdBtrntEywVtFn3gjKU6FpWyNXs3obuB.YzRd5NZjmqb3FQlAgpSS9g"
      }
}

# Valid ID modes for catalog output
VALID_ID_MODES = {'mal', 'imdb', 'tvdb'}


def get_manifest_for_mode(id_mode: str) -> dict:
    """Get manifest adjusted for the selected ID mode."""
    manifest = dict(MANIFEST)
    if id_mode == 'imdb':
        manifest = {**manifest, 'id': 'com.skoruppa.docchi-stremio-addon-imdb', 'idPrefixes': ['tt', 'mal', 'kitsu', 'tvdb']}
    elif id_mode == 'tvdb':
        manifest = {**manifest, 'id': 'com.skoruppa.docchi-stremio-addon-tvdb', 'idPrefixes': ['tvdb', 'mal', 'kitsu', 'tt']}
    return manifest


@manifest_router.get('/manifest.json')
async def addon_manifest(request: Request):
    """Provides the manifest for the addon"""
    from config import Config

    # Detect ID mode from URL prefix
    path = request.url.path
    id_mode = 'mal'  # default
    for mode in VALID_ID_MODES:
        if f'/{mode}/' in path:
            id_mode = mode
            break
    # VIP path = imdb mode (backward compat)
    if Config.VIP_PATH in path and id_mode == 'mal':
        id_mode = 'imdb'

    manifest = get_manifest_for_mode(id_mode)
    return respond_with(manifest, 7200)
