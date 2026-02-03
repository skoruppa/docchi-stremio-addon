import re
import aiohttp
from bs4 import BeautifulSoup
from app.utils.common_utils import get_random_agent

# Domains handled by this player
DOMAINS = ['vidnest.io']
NAMES = ['vidnest']


async def get_video_from_vidnest_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """
    Extract video URL from Vidnest player.
    Video URL is directly in jwplayer setup with label containing quality info.
    """
    try:
        headers = {
            "User-Agent": get_random_agent(),
            "Referer": "https://vidnest.io/"
        }

        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            html_content = await response.text()

        # Extract jwplayer setup with sources
        # Pattern: sources: [{file:"URL",label:"1920x1080 2311 kbps"}]
        pattern = r'sources:\s*\[\{file:"([^"]+)",label:"([^"]+)"\}\]'
        match = re.search(pattern, html_content)

        if not match:
            print("Vidnest Player Error: No video source found")
            return None, None, None

        stream_url = match.group(1)
        label = match.group(2)

        # Extract quality from label (e.g., "1920x1080 2311 kbps" -> "1080p")
        quality = "unknown"
        quality_match = re.search(r'(\d+)x(\d+)', label)
        if quality_match:
            quality = f"{quality_match.group(2)}p"

        stream_headers = {'request': headers}

        return stream_url, quality, stream_headers

    except Exception as e:
        print(f"Vidnest Player Error: {e}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://vidnest.io/embed-5xsbjc4ohpyo.html",
    ]

    run_tests(get_video_from_vidnest_player, urls_to_test)
