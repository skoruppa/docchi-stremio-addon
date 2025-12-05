import logging
import aiohttp
import base64
import json
from bs4 import BeautifulSoup
from app.routes.utils import get_random_agent
from aiocache import cached
from aiocache.serializers import PickleSerializer
from app.players.rumble import get_video_from_rumble_player


DECRYPT_API_KEY = "303a897d-sd12-41a8-84d1-5e4f5e208878"


async def check_url_status(session, url):
    try:
        async with session.head(url, allow_redirects=True, timeout=15) as resp:
            if resp.status not in (405, 501):
                return resp.status
    except:
        pass

    try:
        async with session.get(url, headers={"Range": "bytes=0-0"}, allow_redirects=True, timeout=15) as resp:
            return resp.status
    except:
        return None


@cached(ttl=50, serializer=PickleSerializer())
async def get_video_from_lycoris_player(url: str):
    user_agent = get_random_agent()
    headers = {"User-Agent": user_agent}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as response:
                response.raise_for_status()
                html = await response.text()

            soup = BeautifulSoup(html, 'html.parser')
            script = soup.find('script', {'type': 'application/json'})

            if not (script and script.string and "episodeInfo" in script.string):
                return None, None, None

            script_content = script.string.strip()
            data = json.loads(script_content)
            body = json.loads(data["body"])

            episode_info = body.get('episodeInfo', {})
            episode_id = episode_info.get('id')

            if not episode_id:
                logging.error("Lycoris Player Error: Episode ID not found.")
                return None, None, None

            # Get encoded video link
            video_link_url = f"https://www.lycoris.cafe/api/watch/getVideoLink?id={episode_id}"
            async with session.get(video_link_url, headers=headers) as link_response:
                link_response.raise_for_status()
                encrypted_text = await link_response.text()

            base64_encoded_data = base64.b64encode(encrypted_text.encode('latin-1')).decode('utf-8')

            decrypt_url = "https://www.lycoris.cafe/api/watch/decryptVideoLink"
            decrypt_headers = {
                "User-Agent": user_agent,
                "x-api-key": DECRYPT_API_KEY,
                "Content-Type": "application/json"
            }
            payload = {"encoded": base64_encoded_data}

            async with session.post(decrypt_url, headers=decrypt_headers, json=payload, timeout=15) as decrypt_response:
                decrypt_response.raise_for_status()
                video_sources = await decrypt_response.json()

            highest_quality = None
            if video_sources.get('FHD'):
                highest_quality = {"url": video_sources['FHD'], 'quality': '1080p'}
            elif video_sources.get('HD'):
                highest_quality = {"url": video_sources['HD'], 'quality': '720p'}
            elif video_sources.get('SD'):
                highest_quality = {"url": video_sources['SD'], 'quality': '480p'}

            if highest_quality:
                url_candidate, quality = highest_quality['url'], highest_quality['quality']
                status = await check_url_status(session, url_candidate)
                if status == 200:
                    return url_candidate, quality, None

            # Fallback to Rumble if primary sources fail
            rumble_url = episode_info.get('rumbleLink')
            if rumble_url:
                return await get_video_from_rumble_player(rumble_url)

            return None, None, None

    except Exception as e:
        logging.error(f"Lycoris Player Error: An unexpected error occurred: {e}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://www.lycoris.cafe/embed?id=181447&episode=10",
    ]

    run_tests(get_video_from_lycoris_player, urls_to_test)