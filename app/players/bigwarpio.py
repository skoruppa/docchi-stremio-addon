import re
import aiohttp
from urllib.parse import urlparse
from app.routes.utils import get_random_agent


async def get_video_from_bigwarp_player(filelink: str):
    dl_url = "https://bigwarp.io/dl"
    final_referer = "https://bigwarp.io/"
    random_agent = get_random_agent()

    try:
        parsed_url = urlparse(filelink)
        path_parts = parsed_url.path.strip('/').split('/')
        if not path_parts:
            return None, None, None

        filename = path_parts[-1]
        if filename.lower().endswith('.html'):
            file_code = filename[:-5]
        else:
            file_code = filename

        file_code = file_code.replace('embed-', '')

        post_data = {
            'op': 'embed',
            'file_code': file_code,
            'auto': '1',
            'referer': filelink
        }

        headers_post = {
            "User-Agent": random_agent,
            "Referer": filelink,
            "Origin": "https://bigwarp.io",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(dl_url, data=post_data, headers=headers_post) as response:
                response.raise_for_status()
                player_html_content = await response.text()

        setup_match = re.search(
            r'jwplayer\("vplayer"\)\.setup\(\s*(\{.*?\})\s*\);',
            player_html_content,
            re.DOTALL | re.IGNORECASE
        )

        source_data = None
        if setup_match:
            setup_config = setup_match.group(1)
            sources_match = re.search(r'sources:\s*\[\s*\{(.*?)\}\s*\]', setup_config, re.DOTALL | re.IGNORECASE)
            if sources_match:
                source_data = sources_match.group(1)
        else:
            sources_match_fallback = re.search(r'sources:\s*\[\s*\{(.*?)\}\s*\]', player_html_content,
                                               re.DOTALL | re.IGNORECASE)
            if sources_match_fallback:
                source_data = sources_match_fallback.group(1)

        if not source_data:
            return None, None, None

        file_url_match = re.search(r'file\s*:\s*"([^"]+)"', source_data, re.IGNORECASE)
        label_match = re.search(r'label\s*:\s*"([^"]+)"', source_data, re.IGNORECASE)

        if not file_url_match:
            return None, None, None

        stream_url = file_url_match.group(1)

        quality = 'unknown'
        if label_match:
            label_string = label_match.group(1)

            resolution_match_xy = re.search(r'(\d+)x(\d{3,4})', label_string)
            if resolution_match_xy:
                quality = f"{resolution_match_xy.group(2)}p"
            else:
                resolution_match_p = re.search(r'\b(\d{3,4})[pP]\b', label_string)
                if resolution_match_p:
                    quality = f"{resolution_match_p.group(1)}p"

        stream_headers = {
            'request': {
                'User-Agent': random_agent,  # Użyj tego samego agenta co w POST
                'Referer': final_referer  # Referer dla samego strumienia
            }
        }

        return stream_url, quality, stream_headers

    except (aiohttp.ClientError, TimeoutError, AttributeError, ValueError, IndexError, Exception):
        return None, None, None

