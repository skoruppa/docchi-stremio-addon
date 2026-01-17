import re
import time
import string
import random
import aiohttp
from urllib.parse import urlparse, urljoin
from app.utils.common_utils import get_random_agent
from app.utils.proxy_utils import generate_proxy_url
from config import Config

DOMAINS = [
    'dood.watch', 'doodstream.com', 'dood.to', 'dood.so', 'dood.cx', 'dood.la', 'dood.ws',
    'dood.sh', 'doodstream.co', 'dood.pm', 'dood.wf', 'dood.re', 'dood.yt', 'dooood.com',
    'dood.stream', 'ds2play.com', 'doods.pro', 'ds2video.com', 'd0o0d.com', 'do0od.com',
    'd0000d.com', 'd000d.com', 'dood.li', 'dood.work', 'dooodster.com', 'vidply.com',
    'all3do.com', 'do7go.com', 'doodcdn.io', 'doply.net', 'vide0.net', 'vvide0.com',
    'd-s.io', 'dsvplay.com', 'myvidplay.com'
]

ENABLED = True

PROXIFY_STREAMS = Config.PROXIFY_STREAMS
STREAM_PROXY_URL = Config.STREAM_PROXY_URL
STREAM_PROXY_PASSWORD = Config.STREAM_PROXY_PASSWORD


async def get_video_from_dood_player(session, player_url, is_vip: bool = False):
    """Extract video URL from DoodStream player. VIP only (or local selfhost without proxy)."""
    # Dood requires VIP
    if not is_vip:
        return None, None, None
    
    parsed = urlparse(player_url)
    video_id = parsed.path.rstrip('/').split('/')[-1]
    
    # Normalize to /e/ endpoint
    url = f"http://dood.to/e/{video_id}"
    headers = {'User-Agent': get_random_agent(), 'Referer': url}
    
    try:
        # Use proxy for API requests if configured
        if PROXIFY_STREAMS:
            user_agent = headers['User-Agent']
            proxied_url = f'{STREAM_PROXY_URL}/proxy/stream?d={url}&api_password={STREAM_PROXY_PASSWORD}&h_user-agent={user_agent}'
            async with session.get(proxied_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                html = await resp.text()
        else:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                html = await resp.text()
        
        if 'Video not found' in html:
            return None, None, None
        
        # Extract pass_md5 path and token
        pass_md5_match = re.search(r'/pass_md5/[\w-]+/([\w-]+)', html)
        if not pass_md5_match:
            return None, None, None
        
        token = pass_md5_match.group(1)
        pass_md5_url = f"http://dood.to{pass_md5_match.group(0)}"
        
        if PROXIFY_STREAMS:
            proxied_pass_url = f'{STREAM_PROXY_URL}/proxy/stream?d={pass_md5_url}&api_password={STREAM_PROXY_PASSWORD}&h_referer={url}'
            async with session.get(proxied_pass_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                base_url = (await resp.text()).strip()
        else:
            async with session.get(pass_md5_url, headers={'Referer': url}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                base_url = (await resp.text()).strip()
        
        # Build final URL
        if 'cloudflarestorage' in base_url:
            final_url = base_url
        else:
            random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
            expiry = int(time.time() * 1000)
            final_url = f"{base_url}{random_str}?token={token}&expiry={expiry}"
        
        # Proxify stream if configured
        if PROXIFY_STREAMS:
            final_url = await generate_proxy_url(
                session, 
                final_url,
                request_headers={'Referer': 'http://dood.to'}
            )
        
        stream_headers = {'request': {'Referer': 'http://dood.to'}}
        return final_url, 'unknown', stream_headers
    
    except Exception:
        return None, None, None