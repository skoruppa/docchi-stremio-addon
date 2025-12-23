import re
import aiohttp
from urllib.parse import urlparse

from app.routes.utils import get_random_agent
from app.players.utils import fetch_resolution_from_m3u8


async def get_video_from_savefiles_player(session: aiohttp.ClientSession, filelink: str):
    random_agent = get_random_agent()

    try:
        parsed_url = urlparse(filelink)
        base_domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
        dl_url = f"{base_domain}/dl"
        file_code = parsed_url.path.split('/')[-1].split('.')[0]

        post_data = {
            'op': 'embed',
            'file_code': file_code,
            'auto': '0'
        }

        headers_post = {
            "User-Agent": random_agent,
            "Referer": filelink,
            "Origin": base_domain,
            "Content-Type": "application/x-www-form-urlencoded"
        }

        async with session.post(dl_url, data=post_data, headers=headers_post, timeout=aiohttp.ClientTimeout(total=15)) as response:
            response.raise_for_status()
            player_html_content = await response.text()

        stream_url_match = re.search(r'sources:\s*\[{file:"([^"]+)"', player_html_content)

        if not stream_url_match:
            return None, None, None

        stream_url = stream_url_match.group(1)

        stream_get_headers = {
            "User-Agent": random_agent,
            "Referer": f"{base_domain}/",
            "Origin": base_domain
        }
        try:
            if 'mp4' not in stream_url:

                    quality = await fetch_resolution_from_m3u8(session, stream_url, stream_get_headers)
            else:
                quality = "unknown"
                label_match = re.search(r'label\s*:\s*"([^"]+)"', player_html_content, re.IGNORECASE)
                if label_match:
                    label_string = label_match.group(1)

                    resolution_match_xy = re.search(r'(\d+)x(\d{3,4})', label_string)
                    if resolution_match_xy:
                        quality = f"{resolution_match_xy.group(2)}p"
                    else:
                        resolution_match_p = re.search(r'\b(\d{3,4})[pP]\b', label_string)
                        if resolution_match_p:
                            quality = f"{resolution_match_p.group(1)}p"
        except Exception:
            quality = "unknown"

        stream_headers = {'request': stream_get_headers}

        return stream_url, quality, stream_headers

    except (aiohttp.ClientError, TimeoutError, AttributeError, ValueError, IndexError, Exception) as e:
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://savefiles.com/e/ko901kakbuho",
        "https://bigwarp.io/e/q8554e8tzewc.html"
    ]

    run_tests(get_video_from_savefiles_player, urls_to_test)