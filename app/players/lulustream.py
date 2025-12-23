import re
import aiohttp

from app.routes.utils import get_random_agent
from app.players.utils import unpack_js


def fix_m3u8_link(link: str) -> str:
    param_order = ['t', 's', 'e', 'f']
    params = re.findall(r'[?&]([^=]*)=([^&]*)', link)

    param_dict = {}
    extra_params = {}

    for i, (key, value) in enumerate(params):
        if not key:
            if i < len(param_order):
                param_dict[param_order[i]] = value
        else:
            extra_params[key] = value

    extra_params['i'] = '0.3'
    extra_params['sp'] = '0'

    base_url = link.split('?')[0]

    fixed_link = base_url + '?' + '&'.join(f"{k}={v}" for k, v in param_dict.items() if k in param_order)

    if extra_params:
        fixed_link += '&' + '&'.join(f"{k}={v}" for k, v in extra_params.items())

    return fixed_link


async def fetch_resolution_from_m3u8(session, m3u8_url, headers):
    m3u8_url = m3u8_url
    async with session.get(m3u8_url, headers=headers, timeout=10) as response:
        response.raise_for_status()
        m3u8_content = await response.text()

    resolution_match = re.search(r'RESOLUTION=\d+x(\d+)', m3u8_content)

    if resolution_match:
        return int(resolution_match.group(1))
    return None


async def get_video_from_lulustream_player(session: aiohttp.ClientSession, filelink):
    headers = {
        "User-Agent": get_random_agent(),
        "Referer": "https://luluvdo.com",
        "Origin": "https://luluvdo.com"
    }

    async with session.get(filelink, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
        response.raise_for_status()
        html_content = await response.text()

    m3u8_match = ""
    player_data = ""
    try:
        if re.search(r"eval\(function\(p,a,c,k,e", html_content):
            player_data = unpack_js(html_content)
            m3u8_match = re.search(r"sources:\[\{file:\"([^\"]+)\"", player_data)
            stream_url = fix_m3u8_link(m3u8_match.group(1))
        else:
            m3u8_match = re.search(r'sources: \[\{file:"(https?://[^"]+)"\}\]', html_content)
            stream_url = m3u8_match.group(1)
        if not m3u8_match or not stream_url:
            print(html_content)
            return None, None, None
    except AttributeError:
        return None, None, None

    try:
        quality = await fetch_resolution_from_m3u8(session, stream_url, headers)
        quality = f'{quality}p'
    except:
        quality = 'unknown'
    stream_headers = {'request': headers}

    return stream_url, quality, stream_headers
