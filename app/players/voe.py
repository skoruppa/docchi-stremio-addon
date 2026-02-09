import re
import json
import base64
import aiohttp
from urllib.parse import urljoin
from app.utils.common_utils import get_random_agent, fetch_resolution_from_m3u8
from app.utils.proxy_utils import generate_proxy_url
from config import Config

# Domains handled by this player
DOMAINS = [
    'voe.sx', 'voe-unblock.com', 'voe-unblock.net', 'voeunblock.com', 'un-block-voe.net',
    'voeunbl0ck.com', 'voeunblck.com', 'voeunblk.com', 'voe-un-block.com', 'jonathansociallike.com',
    'voeun-block.net', 'v-o-e-unblock.com', 'edwardarriveoften.com', 'nathanfromsubject.com',
    'audaciousdefaulthouse.com', 'launchreliantcleaverriver.com', 'kennethofficialitem.com',
    'reputationsheriffkennethsand.com', 'fittingcentermondaysunday.com', 'lukecomparetwo.com',
    'housecardsummerbutton.com', 'fraudclatterflyingcar.com', 'wolfdyslectic.com',
    'bigclatterhomesguideservice.com', 'uptodatefinishconferenceroom.com', 'jayservicestuff.com',
    'realfinanceblogcenter.com', 'tinycat-voe-fashion.com', 'paulkitchendark.com',
    'metagnathtuggers.com', 'gamoneinterrupted.com', 'chromotypic.com', 'crownmakermacaronicism.com',
    'generatesnitrosate.com', 'yodelswartlike.com', 'figeterpiazine.com', 'strawberriesporail.com',
    'valeronevijao.com', 'timberwoodanotia.com', 'apinchcaseation.com', 'nectareousoverelate.com',
    'nonesnanking.com', 'smoki.cc', 'chuckle-tube.com', 'goofy-banana.com'
]
DOMAINS += [f'voeunblock{x}.com' for x in range(1, 11)]
NAMES = ['voe']

# NOTE: Enabled only for VIP, as whole stream needs to go through proxy
ENABLED = True

PROXIFY_STREAMS = Config.PROXIFY_STREAMS
STREAM_PROXY_URL = Config.STREAM_PROXY_URL
STREAM_PROXY_PASSWORD = Config.STREAM_PROXY_PASSWORD


def voe_decode(ct: str, luts: str) -> dict:
    """Decode VOE encrypted data."""
    lut = [''.join([('\\' + x) if x in '.*+?^${}()|[]\\' else x for x in i]) for i in luts[2:-2].split("','")]
    
    txt = ''
    for i in ct:
        x = ord(i)
        if 64 < x < 91:
            x = (x - 52) % 26 + 65
        elif 96 < x < 123:
            x = (x - 84) % 26 + 97
        txt += chr(x)
    
    for i in lut:
        txt = re.sub(i, '', txt)
    
    ct = base64.b64decode(txt).decode('utf-8')
    txt = ''.join([chr(ord(i) - 3) for i in ct])
    txt = base64.b64decode(txt[::-1]).decode('utf-8')
    
    return json.loads(txt)


async def get_video_from_voe_player(session: aiohttp.ClientSession, player_url: str, is_vip: bool = False):
    """Extract video URL from VOE player. VIP only (or local selfhost without proxy)."""
    # VOE requires VIP (unless FORCE_VIP_PLAYERS is enabled)
    if not is_vip and not Config.FORCE_VIP_PLAYERS:
        return None, None, None
    
    try:
        headers = {
            "User-Agent": get_random_agent(),
            "Referer": player_url
        }
        
        if PROXIFY_STREAMS:
            user_agent = headers['User-Agent']
            proxied_url = f'{STREAM_PROXY_URL}/proxy/stream?d={player_url}&api_password={STREAM_PROXY_PASSWORD}&h_user-agent={user_agent}'
            async with session.get(proxied_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                html_content = await response.text()
        else:
            async with session.get(player_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                html_content = await response.text()
        
        # Check for redirect
        if 'const currentUrl' in html_content:
            redirect_match = re.search(r"window\.location\.href\s*=\s*'([^']+)'", html_content)
            if redirect_match:
                player_url = redirect_match.group(1)
                if PROXIFY_STREAMS:
                    user_agent = headers['User-Agent']
                    proxied_url = f'{STREAM_PROXY_URL}/proxy/stream?d={player_url}&api_password={STREAM_PROXY_PASSWORD}&h_user-agent={user_agent}'
                    async with session.get(proxied_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        response.raise_for_status()
                        html_content = await response.text()
                else:
                    async with session.get(player_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        response.raise_for_status()
                        html_content = await response.text()
        
        # Try new decoding method
        match = re.search(r'json">\["([^"]+)"]</script>\s*<script\s*src="([^"]+)', html_content)
        if match:
            encrypted_data = match.group(1)
            script_url = urljoin(player_url, match.group(2))
            
            async with session.get(script_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                script_content = await response.text()
            
            repl_match = re.search(r"(\[(?:'\W{2}'[,\]]){1,9})", script_content)
            if repl_match:
                decoded = voe_decode(encrypted_data, repl_match.group(1))
                
                # Extract stream URL
                stream_url = None
                for key in ['file', 'source', 'direct_access_url']:
                    if key in decoded:
                        stream_url = decoded[key]  # Keep full URL with parameters
                        break
                
                if stream_url:
                    if PROXIFY_STREAMS:
                        stream_url = await generate_proxy_url(session, stream_url, '/proxy/hls/manifest.m3u8', request_headers=headers)
                    
                    try:
                        quality = await fetch_resolution_from_m3u8(session, stream_url, headers) or "unknown"
                    except Exception:
                        quality = "unknown"
                    
                    stream_headers = {'request': headers}
                    return stream_url, quality, stream_headers
        
        # Fallback: try direct patterns
        patterns = [
            r"mp4[\"']:\s*[\"'](?P<url>[^\"']+)[\"'],\s*[\"']video_height[\"']:\s*(?P<label>[^,]+)",
            r"hls':\s*'(?P<url>[^']+)'",
            r'hls":\s*"(?P<url>[^"]+)",\s*"video_height":\s*(?P<label>[^,]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html_content)
            if match:
                stream_url = match.group('url')
                quality = match.groupdict().get('label', 'unknown')
                
                if stream_url.endswith('.m3u8'):
                    if PROXIFY_STREAMS:
                        proxied_stream_url = await generate_proxy_url(session, stream_url, '/proxy/hls/manifest.m3u8', request_headers=headers)
                    else:
                        proxied_stream_url = stream_url
                    
                    try:
                        quality = await fetch_resolution_from_m3u8(session, proxied_stream_url, headers) or quality
                    except Exception:
                        pass
                
                stream_headers = {'request': headers}
                return stream_url, quality, stream_headers
        
        return None, None, None
        
    except Exception as e:
        print(f"VOE Player Error: {e}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://voe.sx/e/mw8a0fo2xeay",
    ]

    run_tests(get_video_from_voe_player, urls_to_test, True)
