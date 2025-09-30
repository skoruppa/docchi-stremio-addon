import re
import aiohttp
from urllib.parse import urlparse

from app.routes.utils import get_random_agent
from app.players.utils import fetch_resolution_from_m3u8


async def get_video_from_savefiles_player(filelink: str):
    random_agent = get_random_agent()

    try:
        parsed_url = urlparse(filelink)
        base_domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
        dl_url = f"{base_domain}/dl"
        file_code = parsed_url.path.split('/')[-1]

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

        async with aiohttp.ClientSession() as session:
            async with session.post(dl_url, data=post_data, headers=headers_post, timeout=30) as response:
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
                quality = await fetch_resolution_from_m3u8(session, stream_url, stream_get_headers)
            except Exception:
                quality = "unknown"

            stream_headers = {'request': stream_get_headers}

            return stream_url, quality, stream_headers

    except (aiohttp.ClientError, TimeoutError, AttributeError, ValueError, IndexError, Exception) as e:
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://savefiles.com/e/ko901kakbuho"
    ]

    run_tests(get_video_from_savefiles_player, urls_to_test)