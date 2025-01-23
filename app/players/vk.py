import re
from bs4 import BeautifulSoup
import aiohttp
from app.routes.utils import get_random_agent
from flask import request

VK_URL = "https://vk.com"


def extract_highest_quality_video(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')

    scripts = soup.find_all('script')

    for script in scripts:
        if "mp4_" in script.text:
            qualities = extract_qualities_from_script(script.text)

            if qualities:
                highest_quality = max(qualities, key=lambda x: int(x.get('quality', '0')))
                return highest_quality['url'], highest_quality['quality']

    return None, None


def extract_qualities_from_script(data):
    pattern = r'"(mp4_\d+)":"(https:\\/\\/[^"]+)"'
    matches = re.findall(pattern, data)
    qualities = []
    for quality, stream_url in matches:
        qualities.append({
            'quality': quality[4:],
            'url': stream_url.replace("\\/", "/")
        })
    return qualities


async def get_video_from_vk_player(url):
    referer = request.headers.get('Referer', None)
    user_agent = request.headers.get('User-Agent', None)

    if not referer or "web.stremio.com" not in str(referer):
        user_agent = get_random_agent()

    request_headers = {"User-Agent": user_agent,
                       "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"}
    video_headers = {
        "request": {
            "User-Agent": user_agent,
            "Accept": "*/*",
            "Origin": VK_URL,
            "Referer": f"{VK_URL}/",
        }}

    if "video_ext" in url:
        url = url.replace("video_ext", "video_embed")

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=request_headers) as response:
            text = await response.text()

    video_url, quality = extract_highest_quality_video(text)
    return video_url, f'{quality}p', video_headers
