import aiohttp
import json
import urllib.parse
from bs4 import BeautifulSoup
from app.routes.utils import get_random_agent

async def on_request_end(session, trace_config_ctx, params):
    print("Ending %s request for %s. I sent: %s" % (params.method, params.url, params.headers))
    print('Sent headers: %s' % params.response.request_info.headers)

def decrypt_url(url: str) -> str:  # for future (?)
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

    # Użyj BeautifulSoup do analizy strony
    soup = BeautifulSoup(html, "html.parser")
    player_div = soup.find("div", id=lambda x: x and x.startswith("mediaplayer"))
    if not player_div or "player_data" not in player_div.attrs:
        print("Nie znaleziono danych odtwarzacza.")
        return None

    # Parsowanie player_data JSON
    player_data = json.loads(player_div["player_data"])
    return player_data


async def get_video_from_cda_player(url: str) -> tuple:
    """Get the highest quality video URL from CDA.pl."""
    async with aiohttp.ClientSession() as session:
        video_data = await fetch_video_data(session, url)
        if not video_data:
            raise ValueError("Nie można pobrać danych wideo.")

        video_id = video_data['video']['id']
        ts = video_data['video']['ts']
        hash2 = video_data['video']['hash2']
        qualities = video_data['video']['qualities']

        highest_quality, quality_id = get_highest_quality(qualities)

        post_data = {
            "jsonrpc": "2.0",
            "method": "videoGetLink",
            "params": [video_id, quality_id, ts, hash2, {}],
            "id": 3,
        }

        headers = {
            "User-Agent": get_random_agent(),
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-Forwarded-For": "87.205.64.184"
        }

        async with session.post("https://www.cda.pl/", headers=headers, json=post_data) as response:
            response.raise_for_status()
            result = await response.json()

        if result.get("result", {}).get("status") == "ok":
            return result["result"]["resp"], highest_quality

        raise ValueError("Failed to fetch video URL.")
