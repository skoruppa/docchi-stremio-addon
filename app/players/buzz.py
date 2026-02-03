import re
import aiohttp
from app.utils.common_utils import get_random_agent
from config import Config

# Domains handled by this player
DOMAINS = ['buzzheavier.com']
NAMES = ['buzz']

PROXIFY_STREAMS = Config.PROXIFY_STREAMS
STREAM_PROXY_URL = Config.STREAM_PROXY_URL
STREAM_PROXY_PASSWORD = Config.STREAM_PROXY_PASSWORD


async def get_video_from_buzz_player(session: aiohttp.ClientSession, player_url: str, is_vip: bool = False):
    try:
        # Extract media_id from URL
        match = re.search(r'(?://|\.)(buzzheavier\.com)/([0-9a-zA-Z]+)', player_url)
        if not match:
            return None, None, None
        
        host = match.group(1)
        media_id = match.group(2)
        
        # Build preview URL
        url = f'https://{host}/{media_id}/preview'
        
        headers = {
            "User-Agent": get_random_agent(),
            "Referer": player_url
        }
        
        if PROXIFY_STREAMS:
            user_agent = headers['User-Agent']
            proxied_url = f'{STREAM_PROXY_URL}/proxy/stream?d={url}&api_password={STREAM_PROXY_PASSWORD}&h_user-agent={user_agent}'
            async with session.get(proxied_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                html_content = await response.text()
        else:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                html_content = await response.text()
        
        # Try to find video source in <source> tag
        source_match = re.search(r'<source\s+src="([^"]+)"', html_content)
        
        if not source_match:
            return None, None, None
        
        stream_url = source_match.group(1)
        
        quality = 'unknown'
        stream_headers = {'request': headers}
        return stream_url, quality, stream_headers
        
    except Exception as e:
        print(f"Buzz Player Error: {e}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://buzzheavier.com/hg1gtctkofos",
    ]

    run_tests(get_video_from_buzz_player, urls_to_test, True)
