import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urlparse


async def get_video_from_sibnet_player(url: str) -> tuple:

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                return None, None, None

            html = await response.text()
            document = BeautifulSoup(html, "html.parser")

            script = document.select_one("script:-soup-contains('player.src')")
            if not script or not script.string:
                return None, None, None

            script_data = script.string

            slug = (
                script_data.split("player.src", 1)[-1]
                .split("src:", 1)[-1]
                .split('"', 2)[1]
            )

            video_headers = {"request": {
                "Referer": url,
            }}

            if "http" in slug:
                video_url = slug
            else:
                host = urlparse(url).netloc
                video_url = f"https://{host}{slug}"

    return video_url, 'unknown', video_headers
