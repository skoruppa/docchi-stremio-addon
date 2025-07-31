import re
import aiohttp
from aiohttp.client_exceptions import ClientConnectorError, ClientResponseError
import json
import urllib.parse
from bs4 import BeautifulSoup
from config import Config


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
    pattern = r"https?://(?:www\.)?cda\.pl/(?:video/)?([\w]+)(?:\?.*)?|https?://ebd\.cda\.pl/\d+x\d+/([\w]+)"
    match = re.match(pattern, url)

    if match:
        video_id = match.group(1) or match.group(2)
        return f"https://ebd.cda.pl/620x368/{video_id}", video_id
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

    soup = BeautifulSoup(html, "html.parser")
    player_div = soup.find("div", id=lambda x: x and x.startswith("mediaplayer"))
    if not player_div or "player_data" not in player_div.attrs:
        print("Nie znaleziono danych odtwarzacza.")
        return None

    player_data = json.loads(player_div["player_data"])
    return player_data


async def get_video_from_cda_player(url: str) -> tuple:
    url, video_id = normalize_cda_url(url)
    if not url:
        return None, None, None

    async with aiohttp.ClientSession() as session:
        video_data = await fetch_video_data(session, url, video_id)
        if not video_data:
            return None, None, None

        qualities = video_data['video']['qualities']
        current_quality = video_data['video']['quality']

        highest_quality, quality_id = get_highest_quality(qualities)
        if quality_id != current_quality:
            url = f'{url}?wersja={highest_quality}'
            video_data = await fetch_video_data(session, url, video_id)
            if not video_data:
                return None, None, None

        file = video_data['video']['file']
        if file:
            video_url = decrypt_url(file)
            quality = highest_quality
        else:
            manifest_url = video_data['video']['manifest']
            if manifest_url:
                encoded_manifest_url = urllib.parse.quote(manifest_url, safe='')
                video_url = f'{Config.PROTOCOL}://{Config.REDIRECT_URL}/cda-proxy?url={encoded_manifest_url}'

                quality = highest_quality
            else:
                raise ValueError("Nie znaleziono ani pliku wideo ani manifestu.")

        if video_url:
            headers = {"request": {"Referer": f"https://ebd.cda.pl/620x368/{video_id}"}}
            return video_url, quality, headers

        raise ValueError("Failed to fetch video URL.")