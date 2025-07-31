from flask import Blueprint, request, Response, abort
import aiohttp
import re
from urllib.parse import quote, unquote

cda_proxy_bp = Blueprint('cda_proxy', __name__)


async def fetch_and_modify_mpd(mpd_url: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(mpd_url) as response:
                response.raise_for_status()
                mpd_content = await response.text()
    except Exception as e:
        print(f"Error when getting MPD: {e}")
        return None

    base_url = mpd_url.rsplit('/', 1)[0]

    def replace_base_url(match):
        relative_path = match.group(1)
        full_url = f"{base_url}/{relative_path}"
        return f"<BaseURL>{full_url}</BaseURL>"

    modified_mpd = re.sub(r'<BaseURL>([^<]+)</BaseURL>', replace_base_url, mpd_content)

    return modified_mpd


@cda_proxy_bp.route('/cda-proxy')
async def cda_proxy():
    encoded_url = request.args.get('url')

    if not encoded_url:
        abort(400, "Brak parametru 'url'")

    try:
        mpd_url = unquote(encoded_url)

        if not mpd_url.startswith(('http://', 'https://')) or 'cda.pl' not in mpd_url:
            abort(400, "Wrong url")

        if not mpd_url.endswith('.mpd'):
            abort(400, "Must be a mpd file")

        modified_mpd = await fetch_and_modify_mpd(mpd_url)

        if not modified_mpd:
            abort(500, "Error while getting a MPD file")

        return Response(
            modified_mpd,
            mimetype='application/dash+xml',
            headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Cache-Control': 'max-age=3600'
            }
        )

    except Exception as e:
        print(f"Błąd w cda_proxy: {e}")
        abort(500, "Błąd serwera")