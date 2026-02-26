import re
import aiohttp
from urllib.parse import urlparse, quote
from app.utils.common_utils import get_random_agent, fetch_resolution_from_m3u8

# Domains handled by this player
DOMAINS = ['dailymotion.com', 'dai.ly']
NAMES = ['dailymotion']


async def get_video_from_dailymotion_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False) -> tuple:
    try:
        # Extract media_id from URL
        pattern = r'(?://|\.)(dailymotion\.com|dai\.ly)(?:/(?:video|embed|sequence|swf|player)' \
                  r'(?:/video|/full)?)?/(?:[a-z0-9]+\.html\?video=)?(?!playlist)([0-9a-zA-Z]+)'
        match = re.search(pattern, url)
        if not match:
            return None, None, None

        media_id = match.group(2)
        
        headers = {
            'User-Agent': get_random_agent(),
            'Referer': 'https://www.dailymotion.com/'
        }
        
        # Warm-up session to get cookies
        async with session.get('https://www.dailymotion.com/', headers=headers, timeout=aiohttp.ClientTimeout(total=3)) as response:
            pass
        
        # Get metadata
        metadata_url = f'https://www.dailymotion.com/player/metadata/video/{media_id}'
        async with session.get(metadata_url, headers=headers, timeout=aiohttp.ClientTimeout(total=3)) as response:
            response.raise_for_status()
            js_result = await response.json()
        
        if js_result.get('error'):
            return None, None, None
        
        quals = js_result.get('qualities')
        if not quals:
            return None, None, None
        
        # Priority 1: MP4
        for q in ['1080', '720', '480', '380', '240']:
            if q in quals:
                for source in quals[q]:
                    if source.get('type') == 'video/mp4':
                        master_url = source.get('url')
                        if master_url:
                            return master_url, f'{q}p', None
        
        # Priority 2: HLS
        auto_qual = quals.get('auto', [])
        if auto_qual:
            master_url = auto_qual[0].get('url')
            if master_url:
                quality = 'unknown'
                try:
                    quality = await fetch_resolution_from_m3u8(session, master_url, headers) or quality
                except Exception:
                    pass
                return master_url, quality, None
        
        return None, None, None
    
    except Exception as e:
        print(f"Dailymotion Player Error: {e}")
        return None, None, None

if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://www.dailymotion.com/embed/video/x9ybkyu"
    ]

    run_tests(get_video_from_dailymotion_player, urls_to_test)