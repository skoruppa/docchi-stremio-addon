import re
import aiohttp
from urllib.parse import urlparse, quote
from app.utils.common_utils import get_random_agent

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
        
        # Fetch master playlist
        async with session.get(master_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            m3u8_content = await response.text()
        
        # Parse m3u8 for best quality
        sources = re.findall(r'NAME="(?P<label>[^"]+)".*(?:,PROGRESSIVE-URI="|\n)(?P<url>[^#]+)', m3u8_content)
        if not sources:
            return None, None, None
        
        # Sort by quality and pick highest
        sources_sorted = sorted(sources, key=lambda x: int(re.sub(r'\D', '', x[0]) or '0'), reverse=True)
        best_quality, stream_url = sources_sorted[0]
        
        # Normalize URL - encode special characters for Stremio compatibility
        parsed = urlparse(stream_url)
        encoded_path = quote(parsed.path, safe='/.')
        stream_url = f"{parsed.scheme}://{parsed.netloc}{encoded_path}"
        
        # Format quality (add 'p' if not present)
        quality = best_quality if 'p' in best_quality.lower() else f'{best_quality}p'
        
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