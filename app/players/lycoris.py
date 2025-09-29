import logging
import aiohttp
import base64
import json
from bs4 import BeautifulSoup
import re
from app.routes.utils import get_random_agent
from aiocache import cached
from aiocache.serializers import PickleSerializer
from app.players.rumble import get_video_from_rumble_player

headers = {"User-Agent": get_random_agent()}

async def check_url_status(session, url):
    try:
        async with session.head(url, allow_redirects=True) as resp:
            if resp.status not in (405, 501):
                return resp.status
    except:
        pass

    try:
        async with session.get(url, headers={"Range": "bytes=0-0"}, allow_redirects=True) as resp:
            return resp.status
    except:
        return None


@cached(ttl=50, serializer=PickleSerializer())
async def get_video_from_lycoris_player(url: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                html = await response.text()

            soup = BeautifulSoup(html, 'html.parser')
            script = soup.find('script', {'type': 'application/json'})

            if script.string and "episodeInfo" in script.string:
                script_content = script.string.strip()

                data = json.loads(script_content)
                body = json.loads(data["body"])

                highest_quality = None
                if body['episodeInfo']['primarySource']['FHD']:
                    highest_quality = {"url": body['episodeInfo']['primarySource']['FHD'], 'quality': 1080}
                elif body['episodeInfo']['primarySource']['HD']:
                    highest_quality = {"url": body['episodeInfo']['primarySource']['HD'], 'quality': 720}
                elif body['episodeInfo']['primarySource']['SD']:
                    highest_quality = {"url": body['episodeInfo']['primarySource']['SD'], 'quality': 480}

                url_candidate, quality = highest_quality['url'], highest_quality['quality']

                status = await check_url_status(session, url_candidate)
                if status != 200:
                    rumble_url = body['episodeInfo'].get('rumbleLink')
                    if rumble_url:
                        rumble = await get_video_from_rumble_player(rumble_url)
                        return rumble
                    return None, None, None

                return url_candidate, quality, None

        return None, None, None
    except Exception as e:
        logging.error(response.text)
        return None, None, None

if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://www.lycoris.cafe/embed?id=178025&episode=12",
    ]

    run_tests(get_video_from_lycoris_player, urls_to_test)