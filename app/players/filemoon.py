import re
import json
import base64
import aiohttp
from binascii import hexlify
from hashlib import sha256
from os import urandom
from time import time
from random import uniform
from urllib.parse import urljoin, urlparse, quote
from Crypto.Cipher import AES
from app.utils.common_utils import get_random_agent, fetch_resolution_from_m3u8
from app.utils.proxy_utils import generate_proxy_url
from config import Config

PROXIFY_STREAMS = Config.PROXIFY_STREAMS
STREAM_PROXY_URL = Config.STREAM_PROXY_URL
STREAM_PROXY_PASSWORD = Config.STREAM_PROXY_PASSWORD



# Domains handled by this player
DOMAINS = ['f16px.com', 'bysesayeveum.com', 'bysetayico.com', 'bysevepoin.com', 'bysezejataos.com',
    'bysekoze.com', 'bysesukior.com', 'bysejikuar.com', 'bysefujedu.com', 'bysedikamoum.com',
    'bysebuho.com', 'byse.sx', 'filemoon.sx', 'filemoon.to', 'filemoon.in', 'filemoon.link', 'filemoon.nl',
    'filemoon.wf', 'cinegrab.com', 'filemoon.eu', 'filemoon.art', 'moonmov.pro', '96ar.com',
    'kerapoxy.cc', 'furher.in', '1azayf9w.xyz', '81u6xl9d.xyz', 'smdfs40r.skin', 'c1z39.com',
    'bf0skv.org', 'z1ekv717.fun', 'l1afav.net', '222i8x.lol', '8mhlloqo.fun', 'f51rm.com',
    'xcoic.com', 'boosteradx.online', 'streamlyplayer.online', 'bysewihe.com', 'byselapuix.com', 'byseqekaho.com']
NAMES = ['filemoon', 'byse']

REDIRECT_DOMAINS = ['boosteradx.online', 'byse.sx']


# NOTE: Requires proxy for IP-bound extraction and stream playback
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


def _b64urlencode(data, strip=True):
    """Base64 URL-safe encode."""
    if isinstance(data, str):
        data = data.encode()
    encoded = base64.urlsafe_b64encode(data).decode()
    if strip:
        encoded = encoded.rstrip('=')
    return encoded


def fp(x=16, y=0.6, z=0.9):
    """Generate fingerprint payload for API auth."""
    v_id = hexlify(urandom(x)).decode()
    d_id = hexlify(urandom(x)).decode()
    ctime = int(time())
    t_data = {
        'viewer_id': v_id,
        'device_id': d_id,
        'confidence': round(uniform(y, z), 2),
        'iat': ctime,
        'exp': ctime + 600
    }
    t_bdata = _b64urlencode(json.dumps(t_data))
    t_sig = _b64urlencode(sha256(t_bdata.encode()).digest())
    token = f'{t_bdata}.{t_sig}'
    t_data.update({'token': token})
    t_data.pop('iat')
    t_data.pop('exp')
    return {'fingerprint': t_data}



async def process_stream_url(session: aiohttp.ClientSession, stream_url: str, headers: dict, url: str) -> tuple:
    """Process stream URL and return final URL, quality, and headers."""
    # Handle relative URLs
    if stream_url.startswith('/'):
        stream_url = urljoin(url, stream_url)
    stream_headers = {'request': headers}
    # Proxify m3u8 if VIP stream proxy is enabled
    if PROXIFY_STREAMS:
        stream_url = await generate_proxy_url(
            session, 
            stream_url, 
            '/proxy/hls/manifest.m3u8',
            request_headers=headers
        )
        stream_headers = None

    # Fetch quality from m3u8
    try:
        quality = await fetch_resolution_from_m3u8(session, stream_url, headers) or "unknown"
    except Exception:
        quality = "unknown"


    return stream_url, quality, stream_headers


async def get_video_from_filemoon_player(session: aiohttp.ClientSession, url: str, is_vip: bool = False):
    """
    Extract video URL from Filemoon/F16Px player.
    Supports both plain JSON sources and AES-GCM encrypted playback data.
    VIP only (or local selfhost without proxy).
    """
    # Filemoon requires VIP (unless FORCE_VIP_PLAYERS is enabled)
    if not is_vip and not Config.FORCE_VIP_PLAYERS:
        return None, None, None
    
    try:
        # Extract media_id from URL
        # Pattern: /e/MEDIA_ID or /d/MEDIA_ID or /download/MEDIA_ID
        pattern = r'/(?:e|d|download)/([0-9a-zA-Z]+)'
        match = re.search(pattern, url)
        
        if not match:
            print("Filemoon Player Error: Invalid URL format")
            return None, None, None
        
        media_id = match.group(1)
        parsed = urlparse(url)
        host = parsed.netloc

        # Redirect domains
        if host in REDIRECT_DOMAINS or host == 'filemoon.to':
            host = 'streamlyplayer.online'
        
        # Build API URL
        ref = f"https://{host}/"
        api_url = f"https://{host}/api/videos/{media_id}/playback"
        
        headers = {
            "User-Agent": get_random_agent(),
            "Referer": ref,
            "Origin": ref.rstrip('/')
        }
        
        form_data = fp()
        
        # Use /proxy/forward for extraction (supports POST, preserves IP binding)
        if PROXIFY_STREAMS:
            user_agent = headers['User-Agent']
            forward_url = f'{STREAM_PROXY_URL}/proxy/forward?d={api_url}&api_password={STREAM_PROXY_PASSWORD}&h_user-agent={user_agent}&h_referer={ref}&h_origin={ref.rstrip("/")}&h_content-type=application/json'
            async with session.post(forward_url, json=form_data, timeout=aiohttp.ClientTimeout(total=5)) as response:
                response.raise_for_status()
                data = await response.json()
        else:
            async with session.post(api_url, headers=headers, json=form_data, timeout=aiohttp.ClientTimeout(total=5)) as response:
                response.raise_for_status()
                data = await response.json()
        
        sources = None
        
        # Try plain sources first
        if data.get('sources'):
            sources = data.get('sources')
        
        # Try encrypted playback data
        if not sources and data.get('playback'):
            pd = data.get('playback')
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
                ct = json.loads(decrypted.decode('latin-1'))
                sources = ct.get('sources')
            except Exception as e:
                print(f"Filemoon Decryption Error: {e}")

        if sources:
            sources_list = [x.get('url') for x in sources if x.get('url')]
            if sources_list:
                stream_url = sources_list[0]
                # Handle relative URLs
                if stream_url.startswith('/'):
                    stream_url = urljoin(api_url, stream_url)
                return await process_stream_url(session, stream_url, headers, url)
        
        print("Filemoon Player Error: No video sources found")
        return None, None, None
        
    except Exception as e:
        print(f"Filemoon Player Error: {e}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://bysesukior.com/e/byapvkkwb35y",
    ]

    run_tests(get_video_from_filemoon_player, urls_to_test, True)
