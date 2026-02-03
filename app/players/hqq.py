"""
HQQ/Waaw/Netu player handler with automatic captcha solving
"""

import re
import json
import base64
import secrets
from urllib.parse import urljoin, quote
from app.utils.common_utils import get_random_agent

ENABLED = False
# it seems that everything should work but even when x&y looks correct, we not always receive response with link. Leaving for learning
DOMAINS = ['waaw.ac', 'netu.ac', 'hqq.ac', 'waaw.tv', 'netu.tv', 'hqq.tv', 'waaw.to', 'netu.to', 'hqq.to', 'doplay.store', 'younetu.com']
NAMES = ['hqq']



async def get_video_from_hqq_player(session, player_url, is_vip: bool = False):
    """
    Extract video URL from HQQ player with automatic captcha solving.
    """
    import asyncio
    
    try:
        from app.utils.hqq_captcha_solver import solve_hqq_captcha
    except ImportError:
        return None, None, None
    
    headers = {'User-Agent': get_random_agent()}
    
    # Get player page
    async with session.get(player_url, headers=headers) as resp:
        html = await resp.text()
    
    # Extract video ID and key
    video_id_match = re.search(r"'videoid':\s*'([^']+)", html)
    video_key_match = re.search(r"'videokey':\s*'([^']+)", html)
    adbn_match = re.search(r"adbn\s*=\s*'([^']+)", html)
    
    if not (video_id_match and video_key_match and adbn_match):
        return None, None, None
    
    video_id = video_id_match.group(1)
    video_key = video_key_match.group(1)
    adbn = adbn_match.group(1)
    
    # Get captcha image
    base_url = urljoin(player_url, '/')
    img_url = urljoin(base_url, 'player/get_player_image.php')
    
    headers.update({
        'Referer': player_url,
        'Origin': base_url.rstrip('/'),
        'X-Requested-With': 'XMLHttpRequest'
    })
    
    data = {"videoid": video_id, "videokey": video_key, "width": 750, "height": 480}
    md5_url = urljoin(base_url, 'player/get_md5.php')
    
    for attempt in range(3):
        # Get fresh captcha image for each attempt
        async with session.post(img_url, json=data, headers=headers) as resp:
            img_json = await resp.json()
        
        if img_json.get('try_again') == '1' or 'Video not found' in str(img_json):
            return None, None, None
        
        hash_img = img_json['hash_image']
        image_b64 = img_json['image'].replace('data:image/jpeg;base64,', '')
        
        try:
            x, y = solve_hqq_captcha(image_b64)
        except Exception as e:
            print(f"HQQ captcha solving error: {e}")
            import traceback
            traceback.print_exc()
            return None, None, None
        
        # Get video URL with captcha solution
        data = {
            'adb': adbn,
            'sh': secrets.token_hex(20),
            'ver': '4',
            'secure': '0',
            'htoken': '',
            'v': player_url.split('/')[-1],
            'token': '',
            'gt': '',
            'embed_from': '0',
            'wasmcheck': 1,
            'adscore': '',
            'click_hash': quote(hash_img),
            'clickx': x,
            'clicky': y,
        }
        
        async with session.post(md5_url, json=data, headers=headers) as resp:
            md5_json = await resp.json()
        
        if md5_json.get("try_again") != "1":
            # Success - decode link
            obf_link = md5_json.get('obf_link', '')
            if obf_link:
                decrypted = decode_hqq_link(obf_link)
                if decrypted:
                    stream_url = f"https:{decrypted}.mp4.m3u8"
                    headers.pop('X-Requested-With', None)
                    return stream_url, None, {'Referer': player_url, 'Origin': base_url.rstrip('/'), 'Accept': '*/*'}
            return None, None, None
        
        # Wrong captcha - retry after 4s
        if attempt < 3:
            await asyncio.sleep(4)
    
    return None, None, None


def decode_hqq_link(obf_link: str) -> str:
    """Decode HQQ obfuscated link."""
    import html
    import re
    
    if not obf_link:
        return ''
    
    # Decode HTML entities (&#39; -> ', etc.)
    obf_link = html.unescape(obf_link)
    
    # Also decode numeric HTML entities like &#39;
    obf_link = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), obf_link)
    
    if len(obf_link) < 2:
        return ''
    
    obf_link = obf_link[1:]  # Remove first char (#)
    result = ''
    
    i = 0
    while i < len(obf_link):
        try:
            if i + 2 < len(obf_link):
                # Parse as hex (02f = 0x02f = 47 = '/')
                char_code = int(obf_link[i:i+3], 16)
                result += chr(char_code)
                i += 3
            else:
                break
        except (ValueError, OverflowError) as e:
            print(f"HQQ decode error at position {i}: {e}")
            break
    
    return result

if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://hqq.tv/e/NEYvTktac2pMOTFtQTNjNUhHUy9EUT09"
    ]

    run_tests(get_video_from_hqq_player, urls_to_test)