import re
import aiohttp

from app.utils.common_utils import get_random_agent, get_packed_data

# Domains handled by this player
DOMAINS = ['vidtube.one']
NAMES = ['vidtube']


def fix_mp4_link(link: str) -> str:
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

    extra_params['i'] = '0.0'
    extra_params['sp'] = '30000'

    base_url = link.split('?')[0]

    fixed_link = base_url + '?' + '&'.join(f"{k}={v}" for k, v in param_dict.items() if k in param_order)

    if extra_params:
        fixed_link += '&' + '&'.join(f"{k}={v}" for k, v in extra_params.items())

    ext_marker = '/.mp4'
    ext_index = fixed_link.index(ext_marker)
    filename_end_slash_index = fixed_link.rindex('/', 0, ext_index)
    filename_part = fixed_link[filename_end_slash_index + 1: ext_index]
    extracted_char = filename_part[-1]

    new_extension_part = f'/{extracted_char}.mp4'
    fixed_link = fixed_link.replace(ext_marker, new_extension_part, 1)
    parts = fixed_link.split('//', 2)
    if len(parts) == 3:
        fixed_link = parts[0] + '//' + parts[1] + '/v/' + parts[2]

    return fixed_link


async def get_video_from_vidtube_player(session: aiohttp.ClientSession, filelink, is_vip: bool = False):
    headers = {
        "User-Agent": get_random_agent(),
        "Referer": "https://vidtube.one/",
    }

    try:
        async with session.get(filelink, headers=headers, timeout=aiohttp.ClientTimeout(total=3)) as response:
            response.raise_for_status()
            html_content = await response.text()

        try:
            packed_data = get_packed_data(html_content)
            if packed_data:
                mp4_match = re.search(r"sources:\[\{file:\"([^\"]+)\"", packed_data)
                stream_url = fix_mp4_link(mp4_match.group(1))
                label_match = re.search(r'label\s*:\s*"([^"]+)"', packed_data, re.IGNORECASE)
            else:
                mp4_match = re.search(r'sources: \[\{file:"(https?://[^"]+)"\}\]', html_content)
                stream_url = mp4_match.group(1)
                label_match = re.search(r'label\s*:\s*"([^"]+)"', html_content, re.IGNORECASE)
            if not mp4_match or not stream_url:
                print(html_content)
                return None, None, None
        except AttributeError:
            return None, None, None


        quality = 'unknown'
        if label_match:
            label_string = label_match.group(1)

            resolution_match_xy = re.search(r'(\d+)x(\d{3,4})', label_string)
            if resolution_match_xy:
                quality = f"{resolution_match_xy.group(2)}p"
            else:
                resolution_match_p = re.search(r'\b(\d{3,4})[pP]\b', label_string)
                if resolution_match_p:
                    quality = f"{resolution_match_p.group(1)}p"
        stream_headers = {'request': headers}

        return stream_url, quality, stream_headers
    except (aiohttp.ClientError, TimeoutError, AttributeError, ValueError, IndexError, Exception):
        return None, None, None