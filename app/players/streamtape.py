import aiohttp
import re
from bs4 import BeautifulSoup
from app.utils.common_utils import get_random_agent
from app.utils.proxy_utils import generate_proxy_url
from config import Config

# Domains handled by this player
DOMAINS = ['streamtape.com', 'streamtape.to']
NAMES = ['streamtape']

# NOTE: Enabled only for VIP, as whole stream needs to go through proxy
ENABLED = True

PROXIFY_STREAMS = Config.PROXIFY_STREAMS
STREAM_PROXY_URL = Config.STREAM_PROXY_URL
STREAM_PROXY_PASSWORD = Config.STREAM_PROXY_PASSWORD


async def get_video_from_streamtape_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """Extract video URL from Streamtape player. VIP only (or local selfhost without proxy)."""
    # Streamtape requires VIP (unless FORCE_VIP_PLAYERS is enabled)
    if not is_vip and not Config.FORCE_VIP_PLAYERS:
        return None, None, None
    
    quality = "unknown"
    base_url = "https://streamtape.com/e/"

    if not url.startswith(base_url):
        parts = url.split("/")
        video_id = parts[4] if len(parts) > 4 else None
        if not video_id:
            return None, None, None
        new_url = base_url + video_id
    else:
        new_url = url

    headers = {
        "User-Agent": get_random_agent(),
        "Referer": new_url,
    }

    try:
        # Use proxy for API requests if configured
        if PROXIFY_STREAMS:
            user_agent = headers['User-Agent']
            proxied_url = f'{STREAM_PROXY_URL}/proxy/stream?d={new_url}&api_password={STREAM_PROXY_PASSWORD}&h_user-agent={user_agent}'
            async with session.get(proxied_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                content = await response.text()
        else:
            async with session.get(new_url, headers=headers, ssl=False, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                content = await response.text()

        soup = BeautifulSoup(content, 'html.parser')
        target_line = "document.getElementById('robotlink')"
        script_tag = soup.find("script", string=lambda text: target_line in text if text else False)
        if not script_tag or not script_tag.string:
            return None, None, None

        script_content = script_tag.string
        first_part = re.search(r'innerHTML = "(.*?)"', script_content)

        # Wyszukaj drugi ciąg zaczynający się od "xcd" i zignoruj początkowy "xcd"
        second_part = re.findall(r'\(\'xcd(.*?)\'\)', script_content)
        stream_data = first_part.group(1)[:-1] + second_part[1]

        stream_url = f'https:/{stream_data}&stream=1'
        
        # Proxify stream if configured
        if PROXIFY_STREAMS:
            stream_url = await generate_proxy_url(
                session, 
                stream_url,
                request_headers=headers
            )
        
        stream_headers = {'request': headers}
        return stream_url, quality, stream_headers
    
    except Exception:
        return None, None, None

if __name__ == '__main__':
    from app.players.test import run_tests
    urls_to_test = [
        "https://streamtape.com/e/4RjVoMZ0zWcKQDb/"
    ]

    run_tests(get_video_from_streamtape_player, urls_to_test, True)