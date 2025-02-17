import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from app.routes.utils import get_random_agent
from config import Config

PROXIFY_STREAMS = Config.PROXIFY_STREAMS
STREAM_PROXY_URL = Config.STREAM_PROXY_URL
STREAM_PROXY_PASSWORD = Config.STREAM_PROXY_PASSWORD


async def get_video_from_sibnet_player(url: str) -> tuple:
    headers = {
        "User-Agent": get_random_agent(),
    }
    if PROXIFY_STREAMS:
        url = f'{STREAM_PROXY_URL}/proxy/stream?d={url}&api_password={STREAM_PROXY_PASSWORD}'
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                print(f'Wrong Status: {response.text}')
                return None, None, None

            html = await response.text()
            document = BeautifulSoup(html, "html.parser")

            script = document.select_one("script:-soup-contains('player.src')")
            if not script or not script.string:
                print(f'Wrong Body: {response.text}')
                return None, None, None

            script_data = script.string

            slug = (
                script_data.split("player.src", 1)[-1]
                .split("src:", 1)[-1]
                .split('"', 2)[1]
            )

            video_headers = {
                "request": {
                    "Referer": url,
                    "User-Agent": headers['User-Agent']
                }
            }

            if "http" in slug:
                video_url = slug
            else:
                host = urlparse(url).netloc
                video_url = f"https://{host}{slug}"

            async with session.head(video_url, headers=video_headers["request"]) as head_response:
                if head_response.status in (301, 302) and "Location" in head_response.headers:
                    location = head_response.headers["Location"]
                    if not location.startswith("http"):
                        location = urljoin(f"https://{host}", location)
                    video_url = location

    return video_url, "unknown", video_headers
