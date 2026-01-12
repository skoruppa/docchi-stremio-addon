import re
import time
import string
import random
from urllib.parse import urlparse
from app.utils.common_utils import get_random_agent

DOMAINS = [
    'dood.watch', 'doodstream.com', 'dood.to', 'dood.so', 'dood.cx', 'dood.la', 'dood.ws',
    'dood.sh', 'doodstream.co', 'dood.pm', 'dood.wf', 'dood.re', 'dood.yt', 'dooood.com',
    'dood.stream', 'ds2play.com', 'doods.pro', 'ds2video.com', 'd0o0d.com', 'do0od.com',
    'd0000d.com', 'd000d.com', 'dood.li', 'dood.work', 'dooodster.com', 'vidply.com',
    'all3do.com', 'do7go.com', 'doodcdn.io', 'doply.net', 'vide0.net', 'vvide0.com',
    'd-s.io', 'dsvplay.com', 'myvidplay.com'
]

ENABLED = True


async def get_video_from_dood_player(session, player_url):
    """Extract video URL from DoodStream player."""
    parsed = urlparse(player_url)
    video_id = parsed.path.rstrip('/').split('/')[-1]
    
    # Normalize to /e/ endpoint
    url = f"http://dood.to/e/{video_id}"
    headers = {'User-Agent': get_random_agent(), 'Referer': url}
    
    try:
        async with session.get(url, headers=headers) as resp:
            html = await resp.text()
        
        if 'Video not found' in html:
            return None, None, None
        
        # Extract pass_md5 path and token
        pass_md5_match = re.search(r'/pass_md5/[\w-]+/([\w-]+)', html)
        if not pass_md5_match:
            return None, None, None
        
        token = pass_md5_match.group(1)
        pass_md5_url = f"http://dood.to{pass_md5_match.group(0)}"
        
        async with session.get(pass_md5_url, headers={'Referer': url}) as resp:
            base_url = (await resp.text()).strip()
        
        # Build final URL
        if 'cloudflarestorage' in base_url:
            final_url = base_url
        else:
            random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
            expiry = int(time.time() * 1000)
            final_url = f"{base_url}{random_str}?token={token}&expiry={expiry}"
        
        return final_url, None, {'Referer': 'http://dood.to'}
    
    except Exception:
        return None, None, None