import re
import json
import hashlib
import aiohttp
from app.routes.utils import get_random_agent
from flask import request

VK_URL = "https://vk.com"


async def handle_waf_challenge(session, url, video_id, request_headers):
    try:
        async with session.get(url, headers=request_headers) as response:
            response_url = str(response.url)
            if response_url.startswith('https://vk.com/429.html?'):
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
            else:  # videoid
                return match.group(1)

    return None


def extract_highest_quality_video(html_content):
    player_params = extract_player_params(html_content)
    if player_params:
        video_url, quality = extract_from_player_params(player_params)
        if video_url:
            return video_url, quality

    video_url, quality = extract_video_alternative_method(html_content)
    if video_url:
        return video_url, quality

    return None, None


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
    if not player_params or 'params' not in player_params:
        return None, None

    params = player_params['params']
    if not params or not isinstance(params, list) or len(params) == 0:
        return None, None

    data = params[0]
    best_url = None
    best_height = 0

    for format_id, format_url in data.items():
        if not isinstance(format_url, str) or not format_url.startswith(('http', '//', 'rtmp')):
            continue

        if format_id.startswith(('url', 'cache')):
            height_match = re.search(r'^(?:url|cache)(\d+)', format_id)
            if height_match:
                height = int(height_match.group(1))
                if height > best_height:
                    best_height = height
                    best_url = format_url

    if best_url:
        return best_url, str(best_height)

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


async def get_video_from_vk_player(url):
    referer = request.headers.get('Referer', None)
    user_agent = request.headers.get('User-Agent', None)

    if not referer or "web.stremio.com" not in str(referer):
        user_agent = get_random_agent()

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
            "User-Agent": user_agent,
            "Accept": "video/webm,video/ogg,video/*;q=0.9,application/ogg;q=0.7,audio/*;q=0.6,*/*;q=0.5",
            "Origin": VK_URL,
            "Referer": f"{VK_URL}/",
            'X-Requested-With': 'XMLHttpRequest',
        }
    }

    video_id = extract_video_id(url)
    if not video_id:
        print("Failed getting video ID from the URL")
        return None, None, None

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

    async with aiohttp.ClientSession() as session:
        try:
            html_content = await handle_waf_challenge(session, embed_url, video_id, request_headers)

            if not html_content:
                async with session.get(embed_url, headers=request_headers, timeout=30) as response:
                    if response.status != 200:
                        return None, None, None
                    html_content = await response.text()

            video_url, quality = extract_highest_quality_video(html_content)

            video_url = video_url.replace("^", "")
            if video_url:
                return video_url, f'{quality}p', video_headers
            else:
                return None, None, None

        except Exception as e:
            print(f"Error extracting VK video: {str(e)}")
            return None, None, None