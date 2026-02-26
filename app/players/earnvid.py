import re
import ast
import aiohttp
from urllib.parse import urlparse, urljoin
from app.utils.common_utils import get_random_agent, fetch_resolution_from_m3u8, get_packed_data

# Domains handled by this player (FileLions/EarnVid family)
DOMAINS = ['earnvid.com', 'vidhide.com', 'vidhidehub.com', 'streamvid.su', 'movearnpre.com',
    'smoothpre.com', 'videoland.sbs', 'peytonepre.com', 'callistanise.com', 'minochinos.com',
    'earnvids.xyz', 'dhtpre.com']
NAMES = ['earnvid']



async def get_video_from_earnvid_player(session: aiohttp.ClientSession, player_url: str, is_vip: bool = False):
    try:
        headers = {
            "User-Agent": get_random_agent(),
            "Referer": player_url
        }
        parsed_url = urlparse(player_url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

        async with session.get(player_url, headers=headers, timeout=aiohttp.ClientTimeout(total=3)) as response:
            response.raise_for_status()
            html_content = await response.text()

        content = get_packed_data(html_content)
        
        # Update headers for stream request
        ref = urljoin(player_url, '/')
        headers.update({'Referer': ref, 'Origin': ref[:-1]})
        
        # Method 1: Try var links object
        links_match = re.search(r'var\s*links\s*=\s*([^;]+)', content)
        if links_match:
            try:
                links = ast.literal_eval(links_match.group(1))
                source = links.get('hls4') or links.get('hls3') or links.get('hls2')
                if source:
                    if source.startswith('/'):
                        source = urljoin(player_url, source)
                    
                    try:
                        quality = await fetch_resolution_from_m3u8(session, source, headers) or "unknown"
                    except Exception:
                        quality = "unknown"
                    
                    return source, quality, {'request': headers}
            except Exception:
                pass
        
        # Method 2: Try sources array
        source_match = re.search(r'sources:\s*\[{file:\s*["\']([^"\']+ )', html_content)
        if source_match:
            source = source_match.group(1)
            
            try:
                quality = await fetch_resolution_from_m3u8(session, source, headers) or "unknown"
            except Exception:
                quality = "unknown"
            
            return source, quality, {'request': headers}

        return None, None, None

    except Exception as e:
        print(f"EarnVid Player Error: {e}")
        return None, None, None

if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://dhtpre.com/embed/grins3nycf6t",
    ]

    run_tests(get_video_from_earnvid_player, urls_to_test, True)