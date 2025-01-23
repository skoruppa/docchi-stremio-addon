import aiohttp
from bs4 import BeautifulSoup
from app.routes.utils import get_random_agent
import json
from flask import request


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

    video_headers = {
        "request": {
            "User-Agent": user_agent
        },
        "response": {
            "Access-Control-Allow-Origin": "*",
            "Content-Type": "video/mp4"
        }
    }

    return highest_quality_video['url'], f"{highest_quality_video['quality']}p", video_headers


async def get_video_from_okru_player(url):
    referer = request.headers.get('Referer', None)
    user_agent = request.headers.get('User-Agent', None)

    if not referer and "web.stremio.com" not in referer:
        user_agent = get_random_agent()
    headers = {"User-Agent": user_agent}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            text = await response.text()

    document = BeautifulSoup(text, "html.parser")
    player_string = document.select_one("div[data-options]")
    if not player_string:
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
