import re
import aiohttp
from bs4 import BeautifulSoup
from app.routes.utils import get_random_agent
import json
from flask import request
from config import Config

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


async def get_video_from_okru_player(url):
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
        async with aiohttp.ClientSession(headers=headers, connector=aiohttp.TCPConnector(verify_ssl=False)) as session:

            api_url = "https://www.ok.ru/dk?cmd=videoPlayerMetadata"
            payload = {'mid': media_id}
            if PROXIFY_STREAMS:
                api_url = f'{STREAM_PROXY_URL}/proxy/stream?d={api_url}&api_password={STREAM_PROXY_PASSWORD}&h_user-agent={user_agent}'

            try:
                async with session.post(api_url, data=payload, headers=headers) as response:
                    if response.status == 200:
                        metadata = await response.json()
                        stream, quality = process_video_json(metadata['videos'])
                        return stream, quality, video_headers
            except:
                pass

            embed_url = f"https://ok.ru/videoembed/{media_id}"
            if PROXIFY_STREAMS:
                embed_url = f'{STREAM_PROXY_URL}/proxy/stream?d={embed_url}&api_password={STREAM_PROXY_PASSWORD}&h_user-agent={user_agent}'

            async with session.get(embed_url) as response:
                text = await response.text()

            document = BeautifulSoup(text, "html.parser")
            player_string_div = document.select_one("div[data-options]")
            if not player_string_div:
                print("OK.ru Error: Nie znaleziono atrybutu 'data-options' w HTML.")
                return None, None, None

            player_data_str = player_string_div.get("data-options", "")
            player_data_cleaned = player_data_str.replace('&quot;', '"').replace('&amp;', '&')

            player_json = json.loads(player_data_cleaned)
            video_json_str = player_json.get('flashvars', {}).get('metadata')

            if not video_json_str:
                return None, None, None

            video_json = json.loads(video_json_str).get('videos')
            if not video_json:
                return None, None, None

            stream, quality = process_video_json(video_json)
            return stream, quality, video_headers
    except:
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://ok.ru/videoembed/4511946705484"
    ]

    run_tests(get_video_from_okru_player, urls_to_test)