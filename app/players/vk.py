import re
import json
import hashlib
import aiohttp
from app.utils.common_utils import get_random_agent
from flask import request

# Domains handled by this player
DOMAINS = ['vk.com', 'vkvideo.ru']
NAMES = ['vk']

VK_URL = "https://vk.com"
VK_API_URL = "https://vk.com/al_video.php?act=show"


async def handle_waf_challenge(session, url, video_id, request_headers):
    try:
        async with session.get(url, headers=request_headers) as response:
            response_url = str(response.url)
            if response_url.startswith('https://vk.com/429.html?') or response.status == 429:
                hash429_cookie = None
                for cookie in session.cookie_jar:
                    if cookie.key == 'hash429':
                        hash429_cookie = cookie.value
                        break

                if hash429_cookie:
                    hash429 = hashlib.md5(hash429_cookie.encode('ascii')).hexdigest()
                    challenge_url = f"{response_url}&key={hash429}"
                    print(f"Dealing with WAF: {challenge_url}")
                    async with session.get(challenge_url, headers=request_headers) as challenge_response:
                        pass
                    async with session.get(url, headers=request_headers) as new_response:
                        return await new_response.text()

            return await response.text()
    except Exception as e:
        print(f"Failed WAF: {e}")
        return None


def extract_video_id(url):
    patterns = [
        r'oid=(-?\d+).*?id=(\d+)',
        r'video(-?\d+_\d+)',
        r'clip(-?\d+_\d+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            if len(match.groups()) == 2:
                return f"{match.group(1)}_{match.group(2)}"
            else:
                return match.group(1)

    return None


async def get_video_via_api(session, video_id, user_agent):
    headers = {
        "User-Agent": user_agent,
        "Referer": f"{VK_URL}/",
        "Origin": VK_URL,
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest"
    }

    data = {
        'act': 'show',
        'al': '1',
        'video': video_id
    }

    try:
        async with session.post(VK_API_URL, data=data, headers=headers) as response:
            text = await response.text()
            if text.startswith('<!--'):
                text = text[4:]

            try:
                js_data = json.loads(text)
                payload = js_data.get('payload')

                player_params = None
                if isinstance(payload, list):
                    def find_player(obj):
                        if isinstance(obj, dict):
                            if 'player' in obj and 'params' in obj['player']:
                                return obj['player']
                            for v in obj.values():
                                res = find_player(v)
                                if res: return res
                        elif isinstance(obj, list):
                            for v in obj:
                                res = find_player(v)
                                if res: return res
                        return None

                    player_data = find_player(payload)
                    if player_data:
                        player_params = {'params': player_data.get('params')}

                if player_params:
                    return extract_from_player_params(player_params)
            except json.JSONDecodeError:
                pass
    except Exception as e:
        pass

    return None, None


def extract_highest_quality_video(html_content):
    files_data = extract_files_section(html_content)
    if files_data:
        video_url, quality = extract_from_player_params({'params': files_data})
        if video_url:
            return video_url, quality

    player_params = extract_player_params(html_content)
    if player_params:
        video_url, quality = extract_from_player_params(player_params)
        if video_url:
            return video_url, quality

    video_url, quality = extract_video_alternative_method(html_content)
    if video_url:
        return video_url, quality

    return None, None


def extract_files_section(html_content):
    search_str = '"files":'
    start_pos = html_content.find(search_str)

    while start_pos != -1:
        json_start = html_content.find('{', start_pos)
        if json_start != -1:
            try:
                files_obj, _ = json.JSONDecoder().raw_decode(html_content[json_start:])

                if any(k.startswith('mp4') or k.startswith('hls') for k in files_obj.keys()):
                    return files_obj
            except json.JSONDecodeError:
                pass

        start_pos = html_content.find(search_str, start_pos + 1)

    return None


def extract_player_params(html_content):
    player_match = re.search(r'var\s+playerParams\s*=\s*({.+?})\s*;\s*\n', html_content)
    if player_match:
        try:
            return json.loads(player_match.group(1))
        except json.JSONDecodeError:
            pass

    patterns = [
        r'window\.PlayerParams\s*=\s*({.+?});',
        r'playerParams\s*:\s*({.+?}),',
        r'"playerParams"\s*:\s*({.+?})',
        r'playerParams\s*=\s*({.+?});',
    ]

    for pattern in patterns:
        match = re.search(pattern, html_content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue

    return None


def extract_from_player_params(player_params):
    if not player_params:
        return None, None

    if 'params' in player_params:
        params = player_params['params']
        if isinstance(params, list) and len(params) > 0:
            data = params[0]
        elif isinstance(params, dict):
            data = params
        else:
            return None, None
    else:
        data = player_params

    best_url = None
    best_height = 0
    hls_url = None

    for format_id, format_url in data.items():
        if not isinstance(format_url, str) or not format_url.startswith(('http', '//', 'rtmp')):
            continue

        if format_id.startswith(('url', 'cache', 'mp4')):
            height_match = re.search(r'(\d+)$', format_id)
            if not height_match:
                height_match = re.search(r'_(\d+)', format_id)

            if height_match:
                height = int(height_match.group(1))
                if height > best_height:
                    best_height = height
                    best_url = format_url

        if format_id in ['hls', 'hls_live', 'hls_ondemand']:
            hls_url = format_url

    if best_url:
        return best_url, str(best_height)

    if hls_url:
        return hls_url, 'HLS'

    return None, None


def extract_video_alternative_method(html_content):
    mp4_patterns = [
        r'"url":\s*"([^"]*\.mp4[^"]*)"',
        r'"src":\s*"([^"]*\.mp4[^"]*)"',
        r'source\s+src="([^"]*\.mp4[^"]*)"',
        r'<source[^>]+src="([^"]*\.mp4[^"]*)"',
    ]

    for pattern in mp4_patterns:
        matches = re.findall(pattern, html_content)
        if matches:
            url = matches[0].replace('\\/', '/')
            if url.startswith('http'):
                quality_match = re.search(r'(\d+)p?\.mp4', url)
                quality = quality_match.group(1) if quality_match else '480'
                return url, quality

    return None, None


async def get_video_from_vk_player(session: aiohttp.ClientSession, url, is_vip: bool = False):
    try:
        user_agent = request.headers.get('User-Agent', None)
    except:
        user_agent = None

    if not user_agent:
        user_agent = get_random_agent("firefox")

    request_headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    }

    video_headers = {
        "request": {
            "User-Agent": user_agent
        }
    }

    # video_headers = None

    video_id = extract_video_id(url)
    if not video_id:
        print("Failed getting video ID from the URL")
        return None, None, None

    video_url, quality = await get_video_via_api(session, video_id, user_agent)

    if video_url:
        video_url = video_url.replace("^", "")
        quality_str = f'{quality}p' if quality != 'HLS' else 'HLS'
        return video_url, quality_str, video_headers

    if "video_ext" in url:
        embed_url = url
    else:
        parts = video_id.split('_')
        if len(parts) == 2:
            embed_url = f"https://vk.com/video_ext.php?oid={parts[0]}&id={parts[1]}"
        else:
            embed_url = url

    if "?" not in embed_url:
        embed_url += "?"
    if "autoplay=0" not in embed_url:
        embed_url += "&autoplay=0"

    try:
        html_content = await handle_waf_challenge(session, embed_url, video_id, request_headers)

        if not html_content:
            async with session.get(embed_url, headers=request_headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    return None, None, None
                html_content = await response.text()

        video_url, quality = extract_highest_quality_video(html_content)

        if video_url:
            video_url = video_url.replace("^", "")
            quality_str = f'{quality}p' if quality != 'HLS' else 'HLS'
            return video_url, quality_str, video_headers
        else:
            return None, None, None

    except Exception as e:
        print(f"Error extracting VK video: {str(e)}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://vk.com/video_ext.php?oid=730161010&id=456239729&hash=ed6702421a50aae8&hd=2"
    ]

    run_tests(get_video_from_vk_player, urls_to_test)