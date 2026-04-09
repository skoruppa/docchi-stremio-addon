import re
import aiohttp
from urllib.parse import urljoin, urlparse
from app.utils.common_utils import get_random_agent, fetch_resolution_from_m3u8

# Domains handled by this player
DOMAINS = ['vidara.so', 'vidara.to', 'streamix.so', 'stmix.io']
NAMES = ['vidara', 'streamix']

ENABLED = True


async def get_video_from_vidara_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """Extract video URL from Vidara/Streamix player."""
    try:
        match = re.search(r'/(?:e|v)/([0-9a-zA-Z]+)', url)
        if not match:
            print("Vidara Player Error: Invalid URL format")
            return None, None, None

        media_id = match.group(1)
        parsed = urlparse(url)
        host = parsed.netloc
        ref = urljoin(url, '/')

        # vidara uses /api/, streamix uses /ajax/
        if 'vidara' in host:
            api_url = f"https://{host}/api/stream"
        else:
            api_url = f"https://{host}/ajax/stream"

        headers = {
            "User-Agent": get_random_agent(),
            "Referer": url,
            "Origin": ref.rstrip('/'),
            "Content-Type": "application/json"
        }

        payload = {"filecode": media_id, "device": "web"}

        async with session.post(api_url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=3)) as response:
            response.raise_for_status()
            data = await response.json()

        streaming_url = data.get('streaming_url')
        if not streaming_url:
            print("Vidara Player Error: No streaming_url in response")
            return None, None, None

        del headers['Content-Type']

        try:
            quality = await fetch_resolution_from_m3u8(session, streaming_url, headers) or "unknown"
        except Exception:
            quality = "unknown"

        stream_headers = {'request': headers}
        return streaming_url, quality, stream_headers

    except Exception as e:
        print(f"Vidara Player Error: {e}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://vidara.to/e/E0PwlcdTTVuTZ",
    ]

    run_tests(get_video_from_vidara_player, urls_to_test)
