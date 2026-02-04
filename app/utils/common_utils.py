"""
Common utilities shared across the application.
"""

import re
import random
import aiohttp
from html.parser import HTMLParser
from app.utils import jsunpack


def get_random_agent(browser: str = None):
    """Get random user agent string."""
    USER_AGENTS_BY_BROWSER = {
        "chrome": [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
        ],
        "firefox": [
            "Mozilla/5.0 (X11; Linux x86_64; rv:143.0) Gecko/20100101 Firefox/143.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/119.0",
        ],
        "safari": [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
        ],
        "opera": [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 OPR/104.0.0.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 OPR/104.0.0.0",
        ]
    }

    if browser and browser.lower() in USER_AGENTS_BY_BROWSER:
        return random.choice(USER_AGENTS_BY_BROWSER[browser.lower()])

    all_agents = [agent for sublist in USER_AGENTS_BY_BROWSER.values() for agent in sublist]
    return random.choice(all_agents)


def get_packed_data(html):
    packed_data = ''
    for match in re.finditer(r'''(eval\s*\(function\(p,a,c,k,e,.*?)</script>''', html, re.DOTALL | re.I):
        r = match.group(1)
        t = re.findall(r'(eval\s*\(function\(p,a,c,k,e,)', r, re.DOTALL | re.IGNORECASE)
        if len(t) == 1:
            if jsunpack.detect(r):
                packed_data += jsunpack.unpack(r)
        else:
            t = r.split('eval')
            t = ['eval' + x for x in t if x]
            for r in t:
                if jsunpack.detect(r):
                    packed_data += jsunpack.unpack(r)
    return packed_data


async def fetch_resolution_from_m3u8(session: aiohttp.ClientSession, m3u8_url: str, headers: dict, use_proxy: bool = False, timeout: int = 2) -> str | None:
    """Extract maximum resolution from m3u8 playlist.
    
    Args:
        session: aiohttp ClientSession
        m3u8_url: URL to m3u8 playlist
        headers: Request headers
        use_proxy: If True, use MediaFlow proxy to fetch m3u8
        timeout: Timeout in seconds (default: 3)
    
    Returns:
        Resolution string (e.g. '1080p') or None
    """
    if use_proxy:
        from config import Config
        user_agent = headers.get('User-Agent', get_random_agent())
        proxied_url = f'{Config.STREAM_PROXY_URL}/proxy/stream?d={m3u8_url}&api_password={Config.STREAM_PROXY_PASSWORD}&h_user-agent={user_agent}'
        async with session.get(proxied_url, timeout=timeout) as response:
            response.raise_for_status()
            m3u8_content = await response.text()
    else:
        async with session.get(m3u8_url, headers=headers, timeout=timeout) as response:
            response.raise_for_status()
            m3u8_content = await response.text()
    
    resolutions = re.findall(r'RESOLUTION=\s*(\d+)x(\d+)', m3u8_content)
    if resolutions:
        max_resolution = max(int(height) for width, height in resolutions)
        return f"{max_resolution}p"
    return None
