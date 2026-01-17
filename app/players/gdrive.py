import re
from bs4 import BeautifulSoup
import aiohttp
from app.utils.common_utils import get_random_agent
from urllib.parse import urlencode

# Domains handled by this player
DOMAINS = ['drive.google.com', 'drive.usercontent.google.com']


def build_video_url(base_url, document):
    url = base_url.split('?')[0]
    params = {
        input_elem["name"]: input_elem["value"]
        for input_elem in document.select("input[type=hidden]")
    }
    query_string = urlencode(params)

    return f"{url}?{query_string}"


async def get_video_from_gdrive_player(session: aiohttp.ClientSession, drive_url: str, is_vip: bool = False):
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", drive_url)
    if not match:
        return None

    item_id = match.group(1)
    video_url = f"https://drive.usercontent.google.com/download?id={item_id}"

    headers = {
        "User-Agent": get_random_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    }

    async with session.get(video_url, headers=headers) as response:
        text = await response.text()

    if 'Error 404 (Not Found)' in text:
        return None, None, None
    elif not text.startswith("<!DOCTYPE html>"):
        return video_url, "unknown", headers

    soup = BeautifulSoup(text, "html.parser")
    quality = "unknown"

    final_video_url = build_video_url(video_url, soup)
    return final_video_url, quality, headers
