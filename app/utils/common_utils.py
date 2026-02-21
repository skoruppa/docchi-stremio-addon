"""
Common utilities shared across the application.
"""

import re
import random
import aiohttp
from config import Config
from app.utils import jsunpack
from async_tls_client import AsyncSession


async def get_fanart_images(imdb_id: str = None, tvdb_id: int = None, tmdb_id: int = None) -> dict:
    """Fetch logo/background/poster from fanart.tv (requires API key) with metahub logo/background fallback."""
    TIMEOUT = aiohttp.ClientTimeout(total=5)
    result = {}
    if Config.FANART_API_KEY and (tvdb_id or tmdb_id or imdb_id):
        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                if tvdb_id:
                    async with session.get(f"https://webservice.fanart.tv/v3/tv/{tvdb_id}?api_key={Config.FANART_API_KEY}") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            result["logo"] = _fanart_first(data.get("hdtvlogo") or data.get("clearlogo"))
                            result["background"] = _fanart_first(data.get("showbackground"))
                            result["poster"] = _fanart_first(data.get("tvposter"))
                if not result.get("logo") and tmdb_id:
                    async with session.get(f"https://webservice.fanart.tv/v3/movies/{tmdb_id}?api_key={Config.FANART_API_KEY}") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            result["logo"] = result.get("logo") or _fanart_first(data.get("hdmovielogo") or data.get("movielogo"))
                            result["background"] = result.get("background") or _fanart_first(data.get("moviebackground"))
                            result["poster"] = result.get("poster") or _fanart_first(data.get("movieposter"))
        except Exception:
            pass
    if imdb_id and not result.get("logo"):
        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                async with session.get(f"https://images.metahub.space/logo/medium/{imdb_id}/img") as r:
                    if r.status == 200:
                        result["logo"] = str(r.url)
                if not result.get("background"):
                    async with session.get(f"https://images.metahub.space/background/medium/{imdb_id}/img") as r:
                        if r.status == 200:
                            result["background"] = str(r.url)
        except Exception:
            pass
    return result


def _fanart_first(array: list) -> str | None:
    if not array:
        return None
    preferred = [e for e in array if not e.get("lang") or e.get("lang") in ("en", "00")]
    entry = (preferred or array)[0]
    return entry.get("url", "").replace("http://", "https://") or None



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
    """Extract maximum resolution from m3u8 playlist using async-tls-client.
    
    Args:
        session: aiohttp ClientSession (cookies will be copied)
        m3u8_url: URL to m3u8 playlist
        headers: Request headers
        use_proxy: If True, use MediaFlow proxy to fetch m3u8
        timeout: Timeout in seconds (default: 2)
    
    Returns:
        Resolution string (e.g. '1080p') or None
    """
    if use_proxy:
        from config import Config
        user_agent = headers.get('User-Agent', get_random_agent())
        proxied_url = f'{Config.STREAM_PROXY_URL}/proxy/stream?d={m3u8_url}&api_password={Config.STREAM_PROXY_PASSWORD}&h_user-agent={user_agent}'
        m3u8_url = proxied_url
    
    try:
        async with AsyncSession(
            client_identifier="chrome_120",
            random_tls_extension_order=True,
            timeout_milliseconds=timeout*1000
        ) as client:
            client.timeout_seconds = None
            cookies = {cookie.key: cookie.value for cookie in session.cookie_jar}
            if cookies:
                await client.add_cookies(cookies, m3u8_url)
            
            response = await client.get(m3u8_url, headers=headers)
            if response.status_code != 200:
                return None
            
            resolutions = re.findall(r'RESOLUTION=\s*(\d+)x(\d+)', response.text)
            if resolutions:
                max_resolution = max(int(height) for width, height in resolutions)
                return f"{max_resolution}p"
        return None
    except Exception:
        return None
