import re
import aiohttp
import json
from app.routes.utils import get_random_agent


async def get_video_from_rumble_player(url):
    headers = {
        "User-Agent": get_random_agent()
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                return None, None, None

            text = await response.text()

    json_pattern = re.compile(r'"ua":\{.*?\}\}\}\}', re.DOTALL)
    match = json_pattern.search(text)

    if not match:
        return None, None, None

    json_str = '{' + match.group(0) + '}'

    data = json.loads(json_str)

    video_data = data['ua']['mp4']

    highest_resolution = max(video_data.keys(), key=lambda res: int(res))
    highest_quality_url = video_data[highest_resolution]['url'].replace('\\/', '/')

    highest_quality_url += "?u=0&b=0"

    stream_headers = {'request': {
        "Range": "bytes=0-",
        "Priority": "u=4",
        "Referer": "https://rumble.com/",
        "User-Agent": headers['User-Agent']
        }
    }

    return highest_quality_url, f"{highest_resolution}p", stream_headers
