from urllib.parse import urlparse

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
        "ultra": 2160,
        "quad": 1440,
        "full": 1080,
        "hd": 720,
        "sd": 480,
        "low": 360,
        "lowest": 240,
        "mobile": 144
    }
    return quality_mapping.get(quality, quality)


def extract_link(item, attr):
    return item.get(attr).replace("\\\\u0026", "&")


def videos_from_json(video_json, user_agent):
    videos = []
    for item in video_json:
        video_url = extract_link(item, 'url')
        quality = item.get('name')
        quality = fix_quality(quality)

        if video_url.startswith("https://"):
            videos.append({'url': video_url, 'quality': quality})
    highest_quality_video = max(videos, key=lambda x: x['quality'])

    # video_headers = {
    #     "request": {
    #         "User-Agent": user_agent,
    #         "Origin": "https://ok.ru",
    #         "Referer": "https://ok.ru/",
    #         "host": urlparse(highest_quality_video['url']).hostname
    #     }
    # }

    return highest_quality_video['url'], f"{highest_quality_video['quality']}p", None


async def get_video_from_okru_player(url):
    referer = request.headers.get('Referer', None)
    user_agent = request.headers.get('User-Agent', None)
    if PROXIFY_STREAMS:
        url = f'{STREAM_PROXY_URL}/proxy/stream?d={url}&api_password={STREAM_PROXY_PASSWORD}'

    if not referer or "web.stremio.com" not in str(referer):
        user_agent = get_random_agent()
    headers = {"User-Agent": user_agent}

    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(verify_ssl=False)) as session:
            async with session.get(url, headers=headers) as response:
                text = await response.text()
    except aiohttp.client_exceptions.ClientConnectorError:
        return None, None, None

    document = BeautifulSoup(text, "html.parser")
    player_string = document.select_one("div[data-options]")
    if not player_string:
        print(document.prettify())
        return None, None, None

    player_data = player_string.get("data-options", "")
    player_json = json.loads(player_data)
    video_json = json.loads(player_json['flashvars']['metadata'])['videos']
    if "ondemandHls" in player_string:
        playlist_url = extract_link(next((video for video in video_json if video['name'] == 'ondemandHls'), None), "ondemandHls")
        return playlist_url, 'unknown'
    elif "ondemandDash" in player_string:
        playlist_url = extract_link(next((video for video in video_json if video['name'] == 'ondemandDash'), None), "ondemandDash")
        return playlist_url, 'unknown'
    else:
        return videos_from_json(video_json, user_agent)
