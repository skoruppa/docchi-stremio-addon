import re
from bs4 import BeautifulSoup
import aiohttp

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
    request_headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    }
    video_headers = {"request": {
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