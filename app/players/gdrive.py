import re
import aiohttp
from urllib.parse import unquote, urlencode
from app.utils.common_utils import get_random_agent

DOMAINS = ['drive.google.com', 'drive.usercontent.google.com']
NAMES = ['gdrive']

ITAG_MAP = {
    '18': '360p', '22': '720p', '37': '1080p', '38': '3072p',
    '59': '480p', '133': '240p', '134': '360p', '135': '480p',
    '136': '720p', '137': '1080p', '138': '2160p', '160': '144p',
    '264': '1440p', '266': '2160p', '298': '720p', '299': '1080p'
}


async def get_video_from_gdrive_player(session: aiohttp.ClientSession, drive_url: str, is_vip: bool = False):
    match = re.search(r'[-\w]{25,}', drive_url)
    if not match:
        return None, None, None

    doc_id = match.group(0)
    info_url = f'https://drive.google.com/get_video_info?docid={doc_id}'

    headers = {'User-Agent': get_random_agent()}

    try:
        async with session.get(info_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status == 403 or response.status == 429:
                return None, None, None
            
            html = await response.text()

        if 'error' in html:
            return None, None, None

        # Parse fmt_stream_map
        fmt_match = re.search(r'fmt_stream_map=([^&]+)', html)
        if not fmt_match:
            return None, None, None

        value = unquote(fmt_match.group(1))
        items = value.split(',')
        
        sources = []
        for item in items:
            parts = item.split('|')
            if len(parts) == 2:
                itag, url = parts
                quality = ITAG_MAP.get(itag, f'unknown [{itag}]')
                sources.append((quality, unquote(url)))

        if not sources:
            return None, None, None

        sources.sort(key=lambda x: int(re.search(r'(\d+)', x[0]).group(1)) if re.search(r'(\d+)', x[0]) else 0, reverse=True)
        
        best_url = sources[0][1]
        best_quality = sources[0][0]

        return best_url, best_quality, None

    except Exception:
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://drive.google.com/file/d/1K-L0D3sZMFFr2uIEX2MY93Z7ov2FMUxM/view"
    ]

    run_tests(get_video_from_gdrive_player, urls_to_test)
