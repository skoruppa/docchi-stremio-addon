import re
from bs4 import BeautifulSoup
import aiohttp
from urllib.parse import urlparse
from app.routes.utils import get_random_agent


async def get_video_from_uqload_player(url: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            text = await response.text()

    parsed_url = urlparse(url)

    soup = BeautifulSoup(text, 'html.parser')
    script_tags = soup.find_all('script')

    headers = {
        "request": {
            "User-Agent": get_random_agent(),
            "Referer": f"{parsed_url.scheme}://{parsed_url.netloc}",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
        }
    }
    quality = "unknown"

    for script in script_tags:
        if script.string and 'sources:' in script.string:
            match = re.search(r'sources:\s*\["(https?.*?\.mp4)"\]', script.string)
            if match:
                return match.group(1), quality, headers

    return None, None, None
