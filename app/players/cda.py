import re
import aiohttp
from aiohttp.client_exceptions import ClientConnectorError, ClientResponseError
import json
import urllib.parse

# Domains handled by this player
DOMAINS = ['m.cda.pl', 'cda.pl', 'www.cda.pl', 'ebd.cda.pl']
NAMES = ['cda']


def decrypt_url(url: str) -> str:
    for p in ("_XDDD", "_CDA", "_ADC", "_CXD", "_QWE", "_Q5", "_IKSDE"):
        url = url.replace(p, "")
    url = urllib.parse.unquote(url)
    b = []
    for c in url:
        f = c if isinstance(c, int) else ord(c)
        b.append(chr(33 + (f + 14) % 94) if 33 <= f <= 126 else chr(f))
    a = "".join(b)
    a = a.replace(".cda.mp4", "")
    a = a.replace(".2cda.pl", ".cda.pl")
    a = a.replace(".3cda.pl", ".cda.pl")
    if "/upstream" in a:
        a = a.replace("/upstream", ".mp4/upstream")
        return "https://" + a
    return "https://" + a + ".mp4"


def normalize_cda_url(url):
    pattern = r"https?://(?:www\.|m\.)?cda\.pl/(?:video/)?([\w]+)(?:\?.*)?|https?://ebd\.cda\.pl/\d+x\d+/([\w]+)"
    match = re.match(pattern, url)

    if match:
        video_id = match.group(1) or match.group(2)
        return f"https://www.cda.pl/video/{video_id}", video_id
    else:
        return None, None


def get_highest_quality(qualities: dict) -> tuple:
    qualities.pop('auto', None)  # worthless quality
    highest_quality = max(qualities.keys(), key=lambda x: int(x.rstrip('p')))
    return highest_quality, qualities[highest_quality]


async def fetch_video_data(session: aiohttp.ClientSession, url: str, video_id: str) -> dict:
    try:
        async with session.get(url) as response:
            response.raise_for_status()
            html = await response.text()
    except (ClientConnectorError, ClientResponseError):
        return None

    if 'age_confirm' in html:
        data = aiohttp.FormData()
        data.add_field('age_confirm', '')
        try:
            async with session.post(url, data=data) as response:
                response.raise_for_status()
                html = await response.text()
        except (ClientConnectorError, ClientResponseError):
            return None

    match = re.search(r'id="mediaplayer[^"]*"[^>]+player_data="([^"]+)"', html)
    if not match:
        match = re.search(r'player_data="([^"]+)"', html)
    if not match:
        return None
    try:
        return json.loads(match.group(1).replace('&quot;', '"'))
    except Exception:
        return None


async def get_video_from_cda_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False) -> tuple:
    url, video_id = normalize_cda_url(url)
    if not url:
        return None, None, None

    headers = None
    video_data = await fetch_video_data(session, url, video_id)
    if not video_data:
        return None, None, None

    qualities = video_data['video']['qualities']
    file = video_data['video']['file']
    current_quality = video_data['video']['quality']
    highest_quality, quality_id = get_highest_quality(qualities)

    if file:
        if quality_id != current_quality:
            url = f'{url}?wersja={highest_quality}'
            video_data = await fetch_video_data(session, url, video_id)
            if not video_data:
                return None, None, None

        file = video_data['video']['file']
    if file:
        url = decrypt_url(file)
        headers = {"request": {"Referer": f"https://ebd.cda.pl/620x368/{video_id}" }}
    else:
        url = video_data['video']['manifest_apple']

    if url:
        return url, highest_quality, headers

    return None, None, None

if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://ebd.cda.pl/1055x594/27664708b6"
    ]

    run_tests(get_video_from_cda_player, urls_to_test)