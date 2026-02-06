import re
import time
import string
import random
from urllib.parse import urlparse
from async_tls_client import AsyncSession

DOMAINS = [    'dood.watch', 'doodstream.com', 'dood.to', 'dood.so', 'dood.cx', 'dood.la', 'dood.ws',
    'dood.sh', 'doodstream.co', 'dood.pm', 'dood.wf', 'dood.re', 'dood.yt', 'dooood.com',
    'dood.stream', 'ds2play.com', 'doods.pro', 'ds2video.com', 'd0o0d.com', 'do0od.com',
    'd0000d.com', 'd000d.com', 'dood.li', 'dood.work', 'dooodster.com', 'vidply.com',
    'all3do.com', 'do7go.com', 'doodcdn.io', 'doply.net', 'vide0.net', 'vvide0.com',
    'd-s.io', 'dsvplay.com', 'myvidplay.com'
]
NAMES = ['dood']

ENABLED = True

async def get_video_from_dood_player(session, player_url, is_vip: bool = False):
    """Extract video URL from DoodStream player"""
    from app.utils.common_utils import fetch_resolution_from_m3u8

    parsed = urlparse(player_url)
    video_id = parsed.path.rstrip('/').split('/')[-1]
    url = f"http://dood.to/e/{video_id}"

    try:
        async with AsyncSession(client_identifier="chrome_120", random_tls_extension_order=True) as client:
            response = await client.get(url, allow_redirects=True)
            html = response.text

            if 'Video not found' in html:
                return None, None, None

            pass_md5_match = re.search(r'/pass_md5/[\w-]+/([\w-]+)', html)
            if not pass_md5_match:
                return None, None, None

            token = pass_md5_match.group(1)
            pass_md5_url = f"http://dood.to{pass_md5_match.group(0)}"

            response = await client.get(pass_md5_url, headers={'Referer': url}, allow_redirects=True)
            base_url = response.text.strip()

            if 'cloudflarestorage' in base_url:
                final_url = base_url
            else:
                random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
                expiry = int(time.time() * 1000)
                final_url = f"{base_url}{random_str}?token={token}&expiry={expiry}"

            # Check quality
            quality = 'unknown'

            stream_headers = {'request': {'Referer': 'http://dood.to'}}
            return final_url, quality, stream_headers

    except Exception:
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://myvidplay.com/e/l1ebnruggzly",
        "https://dood.yt/e/aorzlvboafi6"
    ]

    run_tests(get_video_from_dood_player, urls_to_test)