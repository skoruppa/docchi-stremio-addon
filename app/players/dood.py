import re
import logging
import aiohttp
import time
import string
import random
from app.utils.common_utils import get_random_agent
from config import Config

# Domains handled by this player
DOMAINS = [
    'dood.watch', 'doodstream.com', 'dood.to', 'dood.so', 'dood.cx', 'dood.la', 'dood.ws',
    'dood.sh', 'doodstream.co', 'dood.pm', 'dood.wf', 'dood.re', 'dood.yt', 'dooood.com',
    'dood.stream', 'ds2play.com', 'doods.pro', 'ds2video.com', 'd0o0d.com', 'do0od.com',
    'd0000d.com', 'd000d.com', 'dood.li', 'dood.work', 'dooodster.com', 'vidply.com',
    'all3do.com', 'do7go.com', 'doodcdn.io', 'doply.net', 'vide0.net', 'vvide0.com',
    'd-s.io', 'dsvplay.com', 'myvidplay.com'
]

ENABLED = False


async def get_video_from_dood_player(session: aiohttp.ClientSession, url):
    user_agent = get_random_agent()
    quality = "unknown"

    dood_host = re.search(r"https?://([^/]+)", url).group(1)
    if dood_host not in ['doodstream.com', 'myvidplay.com']:
        dood_host = 'myvidplay.com'
    
    headers = {
        'User-Agent': user_agent,
        'Referer': f'https://{dood_host}/'
    }

    try:
        async with session.get(url, headers=headers) as response:
            web_url = str(response.url)
            if web_url != url:
                dood_host = re.search(r"https?://([^/]+)", web_url).group(1)
            
            headers['Referer'] = web_url
            html = await response.text()

        # Check for iframe
        iframe_match = re.search(r'<iframe\s*src="([^"]+)', html)
        if iframe_match:
            iframe_url = iframe_match.group(1)
            if not iframe_url.startswith('http'):
                iframe_url = f"https://{dood_host}{iframe_url}"
            
            async with session.get(iframe_url, headers=headers) as iframe_response:
                html = await iframe_response.text()
        else:
            # Try /e/ endpoint
            e_url = url.replace('/d/', '/e/')
            async with session.get(e_url, headers=headers) as e_response:
                html = await e_response.text()

        # Extract token and pass_md5 URL
        match = re.search(r"dsplayer\.hotkeys[^']+\'([^']+).+?function\s*makePlay.+?return[^?]+([^\"]+)", html, re.DOTALL)
        if not match:
            return None, None, None

        pass_md5_path = match.group(1)
        token = match.group(2)
        
        pass_md5_url = f"https://{dood_host}{pass_md5_path}"
        async with session.get(pass_md5_url, headers=headers) as token_response:
            base_url = await token_response.text()
            base_url = base_url.strip()

        # Generate random string and build final URL
        random_string = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
        expiry = int(time.time() * 1000)
        final_url = f"{base_url}{random_string}{token}{expiry}"
        
        stream_headers = {"request": {"Referer": web_url, "User-Agent": user_agent}}
        return final_url, quality, stream_headers

    except Exception as e:
        logging.error(f"Dood Player Error: {e}")
        return None, None, None