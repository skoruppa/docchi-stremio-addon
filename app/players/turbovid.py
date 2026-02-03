import re
import aiohttp
from app.utils.common_utils import get_random_agent, fetch_resolution_from_m3u8

# Domains handled by this player
DOMAINS = ['turboviplay.com', 'emturbovid.com', 'tuborstb.co', 'javggvideo.xyz', 'stbturbo.xyz', 'turbovidhls.com']
NAMES = ['turbovid']


async def get_video_from_turbovid_player(session: aiohttp.ClientSession, player_url: str, is_vip: bool = False):
    try:
        # Extract media_id from URL
        match = re.search(r'(?://|\.)((?:turboviplay|(?:em)?turbovid(?:hls)?|tuborstb|javggvideo|stbturbo)\.(?:com?|xyz))/(?:t/|d/)?([0-9a-zA-Z]+)', player_url)
        if not match:
            return None, None, None
        
        host = match.group(1)
        media_id = match.group(2)
        
        # Build URL
        url = f'https://{host}/t/{media_id}'
        
        headers = {
            "User-Agent": get_random_agent(),
            "Referer": player_url
        }
        
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            html_content = await response.text()
        
        # Try to find urlPlay or data-hash
        source_match = re.search(r'''(?:urlPlay|data-hash)\s*=\s*['"](?P<url>[^"']+)''', html_content)
        
        if not source_match:
            return None, None, None
        
        stream_url = source_match.group('url')
        
        try:
            quality = await fetch_resolution_from_m3u8(session, stream_url, headers) or "unknown"
        except Exception:
            quality = "unknown"
        
        stream_headers = {'request': headers}
        return stream_url, quality, stream_headers
        
    except Exception as e:
        print(f"TurboVid Player Error: {e}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://turbovidhls.com/t/6981d1ded9585",
    ]

    run_tests(get_video_from_turbovid_player, urls_to_test, True)
