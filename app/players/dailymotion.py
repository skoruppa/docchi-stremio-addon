import re
import aiohttp
from urllib.parse import urlparse, quote
from app.utils.common_utils import get_random_agent, fetch_resolution_from_m3u8

# Domains handled by this player
DOMAINS = ['dailymotion.com', 'dai.ly']


async def get_video_from_dailymotion_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False) -> tuple:
    try:
        # Extract media_id from URL
        pattern = r'(?://|\.)(dailymotion\.com|dai\.ly)(?:/(?:video|embed|sequence|swf|player)' \
                  r'(?:/video|/full)?)?/(?:[a-z0-9]+\.html\?video=)?(?!playlist)([0-9a-zA-Z]+)'
        match = re.search(pattern, url)
        if not match:
            return None, None, None
        
        media_id = match.group(2)
        
        # Build metadata URL
        metadata_url = f'https://www.dailymotion.com/player/metadata/video/{media_id}'
        
        headers = {
            'User-Agent': get_random_agent(),
            'Origin': 'https://www.dailymotion.com',
            'Referer': 'https://www.dailymotion.com/'
        }
        
        async with session.get(metadata_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            js_result = await response.json()
        
        if js_result.get('error'):
            return None, None, None
        
        quals = js_result.get('qualities')
        if not quals:
            return None, None, None
        
        # Get auto quality master playlist
        auto_qual = quals.get('auto', [])
        if not auto_qual:
            return None, None, None
        
        master_url = auto_qual[0].get('url')
        if not master_url:
            return None, None, None
        
        # Normalize master URL - encode only path, preserve query string
        parsed = urlparse(master_url)
        encoded_path = quote(parsed.path, safe='/.')
        stream_url = f"{parsed.scheme}://{parsed.netloc}{encoded_path}"
        if parsed.query:
            stream_url += f"?{parsed.query}"
        
        # Fetch quality from master m3u8
        try:
            quality = await fetch_resolution_from_m3u8(session, stream_url, headers) or "unknown"
        except Exception:
            quality = "unknown"
        
        stream_headers = {'request': headers}
        return stream_url, quality, stream_headers
    
    except Exception as e:
        print(f"Dailymotion Player Error: {e}")
        return None, None, None

if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://www.dailymotion.com/embed/video/x9ybkyu"
    ]

    run_tests(get_video_from_dailymotion_player, urls_to_test)