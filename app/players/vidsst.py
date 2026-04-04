import re
import aiohttp
from app.utils.common_utils import get_random_agent, fetch_resolution_from_m3u8

# Domains handled by this player
DOMAINS = ['vids.st']
NAMES = ['vidsst', 'vids']


async def get_video_from_vidsst_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """
    Extract video URL from vids.st player.
    The m3u8 URL is directly in the page HTML in a JS variable.
    """
    try:
        headers = {
            "User-Agent": get_random_agent(),
            "Referer": "https://vids.st/"
        }

        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=3)) as response:
            response.raise_for_status()
            html_content = await response.text()

        # Extract m3u8 URL from: const url = "https://cdn.vids.st/...master.m3u8";
        match = re.search(r'const\s+url\s*=\s*"([^"]+\.m3u8[^"]*)"', html_content)
        if not match:
            print("Vids.st Player Error: No m3u8 URL found")
            return None, None, None

        stream_url = match.group(1).replace('\\/', '/')

        try:
            quality = await fetch_resolution_from_m3u8(session, stream_url, headers) or "unknown"
        except Exception:
            quality = "unknown"

        return stream_url, quality, None

    except Exception as e:
        print(f"Vids.st Player Error: {e}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://vids.st/e/5741",
    ]

    run_tests(get_video_from_vidsst_player, urls_to_test)
