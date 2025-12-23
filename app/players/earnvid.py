import re
import aiohttp
from urllib.parse import urlparse
from app.routes.utils import get_random_agent
from app.players.utils import unpack_js
from app.players.utils import fetch_resolution_from_m3u8


async def get_video_from_earnvid_player(session: aiohttp.ClientSession, player_url: str):
    try:
        headers = {
            "User-Agent": get_random_agent(),
            "Referer": player_url
        }
        parsed_url = urlparse(player_url)
        base_url_with_scheme = f"{parsed_url.scheme}://{parsed_url.netloc}"

        async with session.get(player_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            html_content = await response.text()

        if not re.search(r"eval\(function\(p,a,c,k,e", html_content):
            return None, None, None

        unpacked_js_code = unpack_js(html_content)

        stream_match = re.search(r'"hls4"\s*:\s*"([^"]+)"', unpacked_js_code)

        if not stream_match:
            return None, None, None

        stream_url = f"{base_url_with_scheme}{stream_match.group(1)}"

        try:
            quality = await fetch_resolution_from_m3u8(session, stream_url, headers) or "unknown"
        except Exception:
            quality = "unknown"

        stream_headers = {'request': headers}

        return stream_url, quality, stream_headers

    except Exception as e:
        print(f"EarnVid Player Error: Unexpected: {e}")
        return None, None, None