import re
import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from app.utils.common_utils import get_random_agent
from config import Config

# Domains handled by this player
DOMAINS = ['uqload.com', 'uqload.co', 'uqload.to']
NAMES = ['uqload']

# NOTE: Enabled only for VIP, as whole stream needs to go through proxy
ENABLED = True

PROXIFY_STREAMS = Config.PROXIFY_STREAMS
STREAM_PROXY_URL = Config.STREAM_PROXY_URL
STREAM_PROXY_PASSWORD = Config.STREAM_PROXY_PASSWORD


async def get_video_from_uqload_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """Extract video URL from Uqload player. VIP only (or local selfhost without proxy)."""
    # Uqload requires VIP (unless FORCE_VIP_PLAYERS is enabled)
    if not is_vip and not Config.FORCE_VIP_PLAYERS:
        return None, None, None
    if "embed-" in url:
        url = url.replace("embed-", "")
    parsed_url = urlparse(url)

    if PROXIFY_STREAMS:
        url = f'{STREAM_PROXY_URL}/proxy/stream?d={url}&api_password={STREAM_PROXY_PASSWORD}'

    headers = {
        "User-Agent": get_random_agent(),
        "Referer": f"{parsed_url.scheme}://{parsed_url.netloc}",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    }

    try:
        async with session.get(url, headers=headers, ssl=False) as response:
            text = await response.text()

        soup = BeautifulSoup(text, 'html.parser')
        try:
            match = re.search(r"\[\d+x(\d+),", soup.find("div", id="forumcode").textarea.text)
        except AttributeError:
            return None, None, None
        quality = f'{match.group(1)}p' if match else "unknown"

        script_tags = soup.find_all('script')

        video_headers = None

        for script in script_tags:
            if script.string and 'sources:' in script.string:
                match = re.search(r'sources:\s*\["(https?.*?\.mp4)"\]', script.string)
                if match:
                    stream_url = match.group(1)
                    if PROXIFY_STREAMS:
                        post_data = {
                            "mediaflow_proxy_url": STREAM_PROXY_URL,
                            "endpoint": "/proxy/stream",
                            "destination_url": stream_url,
                            "expiration": 7200,
                            "request_headers": headers,
                            "api_password": STREAM_PROXY_PASSWORD,
                        }
                        async with session.post(f'{STREAM_PROXY_URL}/generate_encrypted_or_encoded_url',
                                                json=post_data) as response:
                            response.raise_for_status()
                            result = await response.json()
                        stream_url = result.get("encoded_url", {})
                    else:
                        video_headers = {'request': headers}
                    return stream_url, quality, video_headers
    except aiohttp.client_exceptions.ClientConnectorError:
        return None, None, None

    return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests
    urls_to_test = [
        "https://uqload.bz/embed-57iyaik6qohj.html"
    ]

    run_tests(get_video_from_uqload_player, urls_to_test, True)