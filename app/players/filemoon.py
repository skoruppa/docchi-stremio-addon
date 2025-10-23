import re
import aiohttp
from urllib.parse import urlparse, urlencode, urljoin
from app.routes.utils import get_random_agent
from app.players.utils import unpack_js
from app.players.utils import fetch_resolution_from_m3u8


def fix_filemoon_m3u8_link(link: str) -> str:
    param_order = ['t', 's', 'e', 'f']

    base_url = link.split('?')[0]
    query_string = link.split('?')[1] if '?' in link else ''

    params_list = query_string.split('&')

    final_params = {}
    keyless_param_index = 0

    for param in params_list:
        if not param:
            continue

        parts = param.split('=', 1)
        key = parts[0]
        value = parts[1] if len(parts) > 1 else ''

        if not key:
            if keyless_param_index < len(param_order):
                final_params[param_order[keyless_param_index]] = value
                keyless_param_index += 1
        else:
            final_params[key] = value

    final_params['p'] = ''

    return f"{base_url}?{urlencode(final_params)}"


async def get_video_from_filemoon_player(player_url: str):
    try:
        parsed_url = urlparse(player_url)
        base_url_with_scheme = f"{parsed_url.scheme}://{parsed_url.netloc}"
        headers = {
            "User-Agent": get_random_agent(),
            "Referer": base_url_with_scheme
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(player_url, headers=headers, timeout=15) as response:
                response.raise_for_status()
                html_content = await response.text()

            iframe_match = re.search(r'<iframe[^>]+src="([^"]+)"', html_content)
            if iframe_match:
                iframe_src = iframe_match.group(1)
                iframe_url = urljoin(player_url, iframe_src)

                async with session.get(iframe_url, headers=headers, timeout=15) as iframe_response:
                    iframe_response.raise_for_status()
                    html_content = await iframe_response.text()

            if not re.search(r"eval\(function\(p,a,c,k,e", html_content):
                return None, None, None

            unpacked_js_code = unpack_js(html_content)
            stream_url_match = re.search(r'sources:\[{file:"([^"]+)"', unpacked_js_code)

            if not stream_url_match:
                print("Filemoon Player Error: No Video")
                return None, None, None

            raw_stream_url = stream_url_match.group(1)

            stream_url = fix_filemoon_m3u8_link(raw_stream_url)

            try:
                quality = await fetch_resolution_from_m3u8(session, stream_url, headers) or "unknown"
            except Exception:
                quality = "unknown"

            stream_headers = {'request': headers}

            return stream_url, quality, stream_headers

    except Exception as e:
        print(f"Filemoon Player Error: Unexpected Error: {e}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://filemoon.sx/e/lxdu2hvivd44",
    ]

    run_tests(get_video_from_filemoon_player, urls_to_test)