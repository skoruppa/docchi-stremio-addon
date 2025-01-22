import re
from bs4 import BeautifulSoup
import aiohttp


async def get_video_from_uqload_player(url: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            text = await response.text()

    soup = BeautifulSoup(text, 'html.parser')
    script_tags = soup.find_all('script')

    headers = {"request": {"Referer": "https://uqload.co/"}}
    quality = "unknown"

    for script in script_tags:
        if script.string and 'sources:' in script.string:
            match = re.search(r'sources:\s*\["(https?.*?\.mp4)"\]', script.string)
            if match:
                return match.group(1), quality, headers

    return None, None, None
