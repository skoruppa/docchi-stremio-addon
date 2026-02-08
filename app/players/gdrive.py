import re
import aiohttp
from app.utils.common_utils import get_random_agent
from urllib.parse import unquote

# Domains handled by this player
DOMAINS = ['drive.google.com', 'drive.usercontent.google.com']
NAMES = ['gdrive']

ITAG_MAP = {
    '5': '240p', '6': '270p', '17': '144p', '18': '360p', '22': '720p', '34': '360p', '35': '480p',
    '36': '240p', '37': '1080p', '38': '3072p', '43': '360p', '44': '480p', '45': '720p', '46': '1080p',
    '82': '360p [3D]', '83': '480p [3D]', '84': '720p [3D]', '85': '1080p [3D]', '100': '360p [3D]',
    '101': '480p [3D]', '102': '720p [3D]', '92': '240p', '93': '360p', '94': '480p', '95': '720p',
    '96': '1080p', '132': '240p', '151': '72p', '133': '240p', '134': '360p', '135': '480p',
    '136': '720p', '137': '1080p', '138': '2160p', '160': '144p', '264': '1440p',
    '298': '720p', '299': '1080p', '266': '2160p', '167': '360p', '168': '480p', '169': '720p',
    '170': '1080p', '218': '480p', '219': '480p', '242': '240p', '243': '360p', '244': '480p',
    '245': '480p', '246': '480p', '247': '720p', '248': '1080p', '271': '1440p', '272': '2160p',
    '302': '2160p', '303': '1080p', '308': '1440p', '313': '2160p', '315': '2160p', '59': '480p'
}


async def get_video_from_gdrive_player(session: aiohttp.ClientSession, drive_url: str, is_vip: bool = False):
    match = re.search(r'[-\w]{25,}', drive_url)
    if not match:
        return None, None, None

    doc_id = match.group(0)
    info_url = f'https://drive.google.com/u/0/get_video_info?docid={doc_id}&drive_originator_app=303'

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0'}

    try:
        async with session.get(info_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
            html = await response.text()
            cookies = {cookie.key: cookie.value for cookie in response.cookies.values()}

        if 'reason=' in html:
            return None, None, None

        fmt_match = re.findall(r'fmt_stream_map=([^&]+)', html)
        if not fmt_match:
            return None, None, None

        value = unquote(fmt_match[0])
        items = value.split(',')
        
        if items:
            for item in reversed(items):
                parts = item.split('|')
                if len(parts) == 2:
                    source_itag, source_url = parts
                    quality = ITAG_MAP.get(source_itag, f'unknown [{source_itag}]')
                    source_url = unquote(source_url)
                    
                    if cookies:
                        cookie_str = '; '.join([f'{k}={v}' for k, v in cookies.items()])
                        headers['Cookie'] = cookie_str
                    
                    return source_url, quality, {'request': headers}

        return None, None, None

    except Exception:
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://drive.google.com/file/d/1fWWNi8bmIV2X5MIcR0ez4BLDWG7kszqM/view"
    ]

    run_tests(get_video_from_gdrive_player, urls_to_test)
