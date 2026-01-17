import re
import json
import base64
import aiohttp
from urllib.parse import urljoin, urlparse, quote
from Crypto.Cipher import AES
from app.utils.common_utils import get_random_agent
from app.utils.proxy_utils import generate_proxy_url
from config import Config

PROXIFY_STREAMS = Config.PROXIFY_STREAMS
STREAM_PROXY_URL = Config.STREAM_PROXY_URL
STREAM_PROXY_PASSWORD = Config.STREAM_PROXY_PASSWORD



# Domains handled by this player
DOMAINS = [
    'f16px.com', 'bysesayeveum.com', 'bysetayico.com', 'bysevepoin.com', 'bysezejataos.com',
    'bysekoze.com', 'bysesukior.com', 'bysejikuar.com', 'bysefujedu.com', 'bysedikamoum.com',
    'bysebuho.com', 'filemoon.sx', 'filemoon.to', 'filemoon.in', 'filemoon.link', 'filemoon.nl',
    'filemoon.wf', 'cinegrab.com', 'filemoon.eu', 'filemoon.art', 'moonmov.pro', '96ar.com',
    'kerapoxy.cc', 'furher.in', '1azayf9w.xyz', '81u6xl9d.xyz', 'smdfs40r.skin', 'c1z39.com',
    'bf0skv.org', 'z1ekv717.fun', 'l1afav.net', '222i8x.lol', '8mhlloqo.fun', 'f51rm.com',
    'xcoic.com', 'boosteradx.online'
]

# NOTE: Enabled only for VIP, as whole stream needs to go through proxy 
ENABLED = True


def ft(e: str) -> bytes:
    """Base64 decode with URL-safe alphabet"""
    t = e.replace("-", "+").replace("_", "/")
    r = 0 if len(t) % 4 == 0 else 4 - len(t) % 4
    n = t + "=" * r
    return base64.b64decode(n)


def xn(e: list) -> bytes:
    """Join multiple base64 decoded parts"""
    t = [ft(part) for part in e]
    return b''.join(t)



async def process_stream_url(session: aiohttp.ClientSession, stream_url: str, quality_label: str, headers: dict, url: str, is_vip: bool = False) -> tuple:
    """Process stream URL and return final URL, quality, and headers."""
    # Handle relative URLs
    if stream_url.startswith('/'):
        stream_url = urljoin(url, stream_url)
    
    # Proxify m3u8 if VIP stream proxy is enabled
    if is_vip and PROXIFY_STREAMS:
        stream_url = await generate_proxy_url(
            session, 
            stream_url, 
            '/proxy/hls/manifest.m3u8',
            request_headers=headers
        )
    
    # Extract quality
    quality = re.sub(r'\D', '', quality_label) + 'p' if quality_label else 'unknown'
    
    stream_headers = {'request': headers}
    return stream_url, quality, stream_headers


async def get_video_from_filemoon_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """
    Extract video URL from Filemoon/F16Px player.
    Supports both plain JSON sources and AES-GCM encrypted playback data.
    VIP only (or local selfhost without proxy).
    """
    # Filemoon requires VIP
    if not is_vip:
        return None, None, None
    
    try:
        # Extract media_id from URL
        # Pattern: /e/MEDIA_ID or /d/MEDIA_ID
        pattern = r'/(?:e|d)/([0-9a-zA-Z]+)'
        match = re.search(pattern, url)
        
        if not match:
            print("Filemoon Player Error: Invalid URL format")
            return None, None, None
        
        media_id = match.group(1)
        parsed = urlparse(url)
        host = parsed.netloc
        
        # Build API URL
        api_url = f"https://{host}/api/videos/{media_id}/embed/playback"
        
        headers = {
            "User-Agent": get_random_agent(),
            "Referer": urljoin(url, '/')
        }
        
        # Use proxy if configured
        if PROXIFY_STREAMS:
            user_agent = headers['User-Agent']
            proxied_url = f'{STREAM_PROXY_URL}/proxy/stream?d={api_url}&api_password={STREAM_PROXY_PASSWORD}&h_user-agent={user_agent}'
            async with session.get(proxied_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                data = await response.json()
        else:
            async with session.get(api_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                data = await response.json()
        
        # Try plain sources first
        sources = data.get('sources')
        if sources:
            sources_list = [(x.get('label', '0'), x.get('url')) for x in sources if x.get('url')]
            if sources_list:
                sources_list.sort(key=lambda x: int(re.sub(r'\D', '', x[0]) or '0'), reverse=True)
                quality_label, stream_url = sources_list[0]
                return await process_stream_url(session, stream_url, quality_label, headers, url, is_vip)
        
        # Try encrypted playback data
        pd = data.get('playback')
        if pd:
            try:
                iv = ft(pd.get('iv'))
                key = xn(pd.get('key_parts'))
                payload = ft(pd.get('payload'))
                
                # AES-GCM: last 16 bytes are the authentication tag
                ciphertext = payload[:-16]
                tag = payload[-16:]
                
                # Decrypt using AES-GCM
                cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
                decrypted = cipher.decrypt_and_verify(ciphertext, tag)
                ct = json.loads(decrypted.decode('utf-8'))
                
                sources = ct.get('sources')
                if sources:
                    sources_list = [(x.get('label', '0'), x.get('url')) for x in sources if x.get('url')]
                    if sources_list:
                        sources_list.sort(key=lambda x: int(re.sub(r'\D', '', x[0]) or '0'), reverse=True)
                        quality_label, stream_url = sources_list[0]
                        return await process_stream_url(session, stream_url, quality_label, headers, url, is_vip)
            except Exception as e:
                print(f"Filemoon Decryption Error: {e}")
        
        print("Filemoon Player Error: No video sources found")
        return None, None, None
        
    except Exception as e:
        print(f"Filemoon Player Error: {e}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://bysesukior.com/e/6u384tt8fz95",
        "https://filemoon.sx/e/lxdu2hvivd44",
    ]

    run_tests(get_video_from_filemoon_player, urls_to_test)
