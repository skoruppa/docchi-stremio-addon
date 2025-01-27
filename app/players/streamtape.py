import aiohttp
import re
from bs4 import BeautifulSoup
from app.routes.utils import get_random_agent


async def get_video_from_streamtape_player(url: str):
    quality = "unknown"
    base_url = "https://streamtape.com/e/"

    if not url.startswith(base_url):
        parts = url.split("/")
        video_id = parts[4] if len(parts) > 4 else None
        if not video_id:
            return None, quality
        new_url = base_url + video_id
    else:
        new_url = url

    headers = {
        "User-Agent": get_random_agent(),
        "Referer": new_url,
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(new_url, headers=headers) as response:
            if response.status != 200:
                return None, None, None
            content = await response.text()

    soup = BeautifulSoup(content, 'html.parser')
    target_line = "document.getElementById('robotlink')"
    script_tag = soup.find("script", string=lambda text: target_line in text if text else False)
    if not script_tag or not script_tag.string:
        return None, None, None

    script_content = script_tag.string
    first_part = re.search(r'innerHTML = "(.*?)"', script_content)

    # Wyszukaj drugi ciąg zaczynający się od "xcd" i zignoruj początkowy "xcd"
    second_part = re.findall(r'\(\'xcd(.*?)\'\)', script_content)

    stream_data = first_part.group(1)[:-1] + second_part[1]

    video_url = f'https:/{stream_data}&stream=1'

    stream_headers = {'request': headers}

    return video_url, quality, stream_headers
