import logging
import aiohttp
import base64
import json
from bs4 import BeautifulSoup
import re
from app.routes.utils import get_random_agent
from aiocache import cached
from aiocache.serializers import PickleSerializer

headers = {"User-Agent": get_random_agent()}
GET_SECONDARY_URL = "https://www.lycoris.cafe/api/watch/getSecondaryLink"
GET_LINK_URL = "https://www.lycoris.cafe/api/watch/getLink"


def decode_video_links(encoded_url):
    if not encoded_url:
        return None

    # Check for our signature
    if not encoded_url.endswith('LC'):
        return encoded_url

    # Remove signature
    encoded_url = encoded_url[:-2]

    try:
        # Reverse the scrambling
        decoded = ''.join(
            chr(ord(char) - 7)  # Shift back
            for char in reversed(encoded_url)  # Reverse back
        )

        # Decode base64
        base64_decoded = base64.b64decode(decoded).decode('utf-8')
        try:
            data = json.loads(base64_decoded)  # Próba załadowania ciągu jako JSON
            return data  # Jeśli nie wystąpi wyjątek, to JSON jest poprawny
        except json.JSONDecodeError:
            return base64_decoded
    except Exception as error:
        print(f"Error decoding URL: {error}")
        return None


async def fetch_and_decode_video(session: aiohttp.ClientSession, episode_id: str, is_secondary: bool = False):
    """
    Pobiera dane wideo z odpowiedniego URL na podstawie parametru is_secondary.
    Jeśli is_secondary jest True, konwertuje link do odpowiedniego formatu.
    """
    try:
        if not is_secondary:
            converted_text = bytes(episode_id, "utf-8").decode("unicode_escape")
            final_text = converted_text.encode("latin1").decode("utf-8")
            params = {"link": final_text}
            url = GET_LINK_URL
        else:
            params = {"id": episode_id}
            url = GET_SECONDARY_URL

        async with session.get(url, params=params, headers=headers) as response:
            response.raise_for_status()
            data = await response.text()
            return decode_video_links(data)

    except aiohttp.ClientError as e:
        logging.error(f"Error during request: {e}")
        return None


def get_highest_quality(video_links):
    quality_map = {
        "SD": 480,
        "HD": 720,
        "FHD": 1080
    }

    filtered_links = {k: v for k, v in video_links.items() if k in quality_map}

    if not filtered_links:
        return None, None

    highest_quality = max(filtered_links.keys(), key=lambda q: quality_map.get(q, 0))
    highest_resolution = f"{quality_map[highest_quality]}p"

    return filtered_links[highest_quality], highest_resolution


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

                # Wybieramy najwyższą jakość
                highest_quality = None
                if body['episodeInfo']['FHD']:
                    highest_quality = {"url": body['episodeInfo']['FHD'], 'quality': 1080}
                elif body['episodeInfo']['HD']:
                    highest_quality = {"url": body['episodeInfo']['HD'], 'quality': 720}
                elif body['episodeInfo']['SD']:
                    highest_quality = {"url": body['episodeInfo']['SD'], 'quality': 480}
                if body['episodeInfo']['id']:
                    video_links = await fetch_and_decode_video(session, body['episodeInfo']['id'], is_secondary=True)
                    if not video_links:
                        video_link = await fetch_and_decode_video(session, highest_quality['url'], is_secondary=False)
                        return video_link, highest_quality['quality']
                    else:
                        return get_highest_quality(video_links)

        return None, None
    except Exception as e:
        logging.error(response.text)
        pass
        return None, None
