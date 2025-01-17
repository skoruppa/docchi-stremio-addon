import re
import aiohttp
import json
import urllib.parse
from bs4 import BeautifulSoup
from app.routes.utils import get_random_agent
from config import Config

PROXIFY_CDA = Config.PROXIFY_CDA
CDA_PROXY_URL = Config.CDA_PROXY_URL
CDA_PROXY_PASSWORD = Config.CDA_PROXY_PASSWORD


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
        return f"https://www.cda.pl/video/{video_id}"
    else:
        # Jeśli URL nie pasuje do wzorca
        return None


def get_highest_quality(qualities: dict) -> tuple:
    """Get the highest quality ID from the qualities dictionary."""
    highest_quality = max(qualities.keys(), key=lambda x: int(x.rstrip('p')))
    return highest_quality, qualities[highest_quality]


async def fetch_video_data(session: aiohttp.ClientSession, url: str) -> dict:
    """Fetch the video player data from the given CDA.pl URL."""
    headers = {"User-Agent": get_random_agent()}
    headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Host": urllib.parse.urlparse(url).netloc,
        "X-Forwarded-For": "87.205.64.184"
    })
    async with session.get(url, headers=headers) as response:
        response.raise_for_status()
        html = await response.text()

    soup = BeautifulSoup(html, "html.parser")
    player_div = soup.find("div", id=lambda x: x and x.startswith("mediaplayer"))
    if not player_div or "player_data" not in player_div.attrs:
        print("Nie znaleziono danych odtwarzacza.")
        return None

    player_data = json.loads(player_div["player_data"])
    return player_data


async def get_video_from_cda_player(url: str) -> tuple:
    """Get the highest quality video URL from CDA.pl."""
    url = normalize_cda_url(url)
    original_url = url
    if PROXIFY_CDA:
        url = f'{CDA_PROXY_URL}/proxy/stream?d={url}&api_password={CDA_PROXY_PASSWORD}'
    async with aiohttp.ClientSession() as session:
        video_data = await fetch_video_data(session, url)
        if not video_data:
            raise ValueError("Nie można pobrać danych wideo.")

        qualities = video_data['video']['qualities']
        current_quality= video_data['video']['quality']

        highest_quality, quality_id = get_highest_quality(qualities)
        if quality_id != current_quality:
            url = f'{original_url}?wersja={highest_quality}'
            if PROXIFY_CDA:
                url = f'{CDA_PROXY_URL}/proxy/stream?d={url}&api_password={CDA_PROXY_PASSWORD}'
            video_data = await fetch_video_data(session, url)
            if not video_data:
                raise ValueError("Nie można pobrać danych wideo.")

        file = video_data['video']['file']
        decrypted_url = decrypt_url(file)
        if PROXIFY_CDA:
            post_data = {
                "mediaflow_proxy_url": CDA_PROXY_URL,
                "endpoint": "/proxy/stream",
                "destination_url": decrypted_url,
                "expiration": 7200,
                "api_password": CDA_PROXY_PASSWORD,
            }
            async with session.post(f'{CDA_PROXY_URL}/generate_encrypted_or_encoded_url', json=post_data) as response:
                response.raise_for_status()
                result = await response.json()
            decrypted_url = result.get("encoded_url", {})

        if decrypted_url:
            return decrypted_url, highest_quality

        raise ValueError("Failed to fetch video URL.")
