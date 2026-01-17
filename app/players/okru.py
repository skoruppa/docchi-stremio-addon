import re
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from app.utils.common_utils import get_random_agent
import json
from flask import request
from config import Config

# Domains handled by this player
DOMAINS = ['ok.ru']

PROXIFY_STREAMS = Config.PROXIFY_STREAMS
STREAM_PROXY_URL = Config.STREAM_PROXY_URL
STREAM_PROXY_PASSWORD = Config.STREAM_PROXY_PASSWORD


def fix_quality(quality):
    quality_mapping = {
        "ultra": 2160, "quad": 1440, "full": 1080, "hd": 720,
        "sd": 480, "low": 360, "lowest": 240, "mobile": 144
    }
    return quality_mapping.get(quality, 0)


def process_video_json(video_json):
    videos = []
    for item in video_json:
        video_url = item.get('url')
        quality_name = item.get('name')

        if video_url and quality_name:
            quality_pixels = fix_quality(quality_name)
            if video_url.startswith("https://") and quality_pixels > 0:
                videos.append({'url': video_url, 'quality': quality_pixels})

    if not videos:
        return None, None

    highest_quality_video = max(videos, key=lambda x: x['quality'])

    return highest_quality_video['url'], f"{highest_quality_video['quality']}p"


async def get_video_from_okru_player(session: aiohttp.ClientSession, url, is_vip: bool = False):
    try:
        user_agent = request.headers.get('User-Agent', None)
    except:
        user_agent = None

    if not user_agent:
        user_agent = get_random_agent("firefox")
    headers = {"User-Agent": user_agent}
    video_headers = {
            "request": {
                "User-Agent": user_agent,
                "Origin": "https://ok.ru",
                "Referer": "https://ok.ru/",
            }
        }
    media_id_match = re.search(r'/video(?:embed)?/(\d+)', url)
    if not media_id_match:
        return None, None, None
    media_id = media_id_match.group(1)

    try:
        api_url = "https://www.ok.ru/dk?cmd=videoPlayerMetadata"
        payload = {'mid': media_id}
        if PROXIFY_STREAMS:
            api_url = f'{STREAM_PROXY_URL}/proxy/stream?d={api_url}&api_password={STREAM_PROXY_PASSWORD}&h_user-agent={user_agent}'

        embed_url = f"https://ok.ru/videoembed/{media_id}"
        if PROXIFY_STREAMS:
            embed_url = f'{STREAM_PROXY_URL}/proxy/stream?d={embed_url}&api_password={STREAM_PROXY_PASSWORD}&h_user-agent={user_agent}'

        # Try both API and embed in parallel
        api_task = session.post(api_url, data=payload, headers=headers)
        embed_task = session.get(embed_url, headers=headers)
        
        results = await asyncio.gather(api_task, embed_task, return_exceptions=True)
        
        # Try API response first
        if not isinstance(results[0], Exception):
            try:
                if results[0].status == 200:
                    metadata = await results[0].json()
                    stream, quality = process_video_json(metadata['videos'])
                    if stream:
                        return stream, quality, video_headers
            except:
                pass
        
        # Fallback to embed response
        if not isinstance(results[1], Exception):
            try:
                text = await results[1].text()
                document = BeautifulSoup(text, "html.parser")
                player_string_div = document.select_one("div[data-options]")
                if player_string_div:
                    player_data_str = player_string_div.get("data-options", "")
                    player_data_cleaned = player_data_str.replace('&quot;', '"').replace('&amp;', '&')
                    player_json = json.loads(player_data_cleaned)
                    video_json_str = player_json.get('flashvars', {}).get('metadata')
                    if video_json_str:
                        video_json = json.loads(video_json_str).get('videos')
                        if video_json:
                            stream, quality = process_video_json(video_json)
                            return stream, quality, video_headers
            except:
                pass
    except:
        pass
    
    return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://ok.ru/videoembed/4511946705484"
    ]

    run_tests(get_video_from_okru_player, urls_to_test)