import re
import json
import base64
import aiohttp
from urllib.parse import urljoin, urlparse
from Crypto.Cipher import AES
from app.utils.common_utils import get_random_agent

# Domains handled by this player
DOMAINS = [
    'f16px.com',
    'bysesayeveum.com',
    'bysetayico.com',
    'bysevepoin.com',
    'bysezejataos.com',
    'bysekoze.com',
    'bysesukior.com'
]


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


async def get_video_from_f16px_player(session: aiohttp.ClientSession, url: str):
    """
    Extract video URL from F16Px player.
    Supports both plain JSON sources and AES-GCM encrypted playback data.
    """
    try:
        # Extract media_id from URL
        # Pattern: /e/MEDIA_ID or /d/MEDIA_ID
        pattern = r'/(?:e|d)/([0-9a-zA-Z]+)'
        match = re.search(pattern, url)
        
        if not match:
            print("F16Px Player Error: Invalid URL format")
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
        
        async with session.get(api_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            data = await response.json()
        
        # Try plain sources first
        sources = data.get('sources')
        if sources:
            # Sort by quality and pick highest
            sources_list = [(x.get('label', '0'), x.get('url')) for x in sources if x.get('url')]
            if sources_list:
                # Sort by quality number (extract digits from label)
                sources_list.sort(key=lambda x: int(re.sub(r'\D', '', x[0]) or '0'), reverse=True)
                quality_label, stream_url = sources_list[0]
                
                # Handle relative URLs
                if stream_url.startswith('/'):
                    stream_url = urljoin(url, stream_url)
                
                # Extract quality (e.g., "1080p" from label)
                quality = re.sub(r'\D', '', quality_label) + 'p' if quality_label else 'unknown'
                
                stream_headers = {'request': headers}
                return stream_url, quality, stream_headers
        
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
                        
                        quality = re.sub(r'\D', '', quality_label) + 'p' if quality_label else 'unknown'
                        
                        stream_headers = {'request': headers}
                        return stream_url, quality, stream_headers
            except Exception as e:
                print(f"F16Px Decryption Error: {e}")
        
        print("F16Px Player Error: No video sources found")
        return None, None, None
        
    except Exception as e:
        print(f"F16Px Player Error: {e}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://bysesukior.com/e/6u384tt8fz95",
    ]

    run_tests(get_video_from_f16px_player, urls_to_test)
