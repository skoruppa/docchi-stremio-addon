import re
import aiohttp

from app.utils.common_utils import get_random_agent, get_packed_data

# Domains handled by this player
DOMAINS = ['luluvdo.com', 'lulu.st']
NAMES = ['lulustream', 'lulu']


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
    async with session.get(m3u8_url, headers=headers, timeout=3) as response:
        response.raise_for_status()
        m3u8_content = await response.text()

    resolution_match = re.search(r'RESOLUTION=\d+x(\d+)', m3u8_content)

    if resolution_match:
        return int(resolution_match.group(1))
    return None


async def get_video_from_lulustream_player(session: aiohttp.ClientSession, filelink, is_vip: bool = False):
    headers = {
        "User-Agent": get_random_agent(),
        "Referer": "https://luluvdo.com",
        "Origin": "https://luluvdo.com"
    }

    async with session.get(filelink, headers=headers, timeout=aiohttp.ClientTimeout(total=3)) as response:
        response.raise_for_status()
        html_content = await response.text()

    try:
        packed_data = get_packed_data(html_content)
        if packed_data:
            m3u8_match = re.search(r"sources:\[\{file:\"([^\"]+)\"", packed_data)
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


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://lulu.st/e/y1i2ys6efo82",
    ]

    run_tests(get_video_from_lulustream_player, urls_to_test, True)