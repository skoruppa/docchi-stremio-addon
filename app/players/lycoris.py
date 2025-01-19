import logging
import aiohttp
import base64
import json
from bs4 import BeautifulSoup
import re
from app.routes.utils import get_random_agent

headers = {"User-Agent": get_random_agent()}
GET_SECONDARY_URL = "https://www.lycoris.cafe/api/getSecondaryLink"
GET_THIRD_URL = "https://www.lycoris.cafe/api/getLink"


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
        if is_secondary:
            converted_text = bytes(episode_id, "utf-8").decode("unicode_escape")
            final_text = converted_text.encode("latin1").decode("utf-8")
            params = {"link": final_text}
            url = GET_THIRD_URL
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


async def get_video_from_lycoris_player(url: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                html = await response.text()

            soup = BeautifulSoup(html, 'html.parser')
            scripts = soup.find_all('script')

            for script in scripts:
                if script.string and "episodeData" in script.string:
                    script_content = script.string.strip()

                    match = re.search(r'episodeData\s*:\s*({.*?}),', script_content, re.DOTALL)
                    if match:
                        episode_data = match.group(1)
                        match = re.search(r'id\s*:\s*(\d+)', episode_data)
                        streams_data = re.findall(r'(FHD|HD|SD):"([^"]+)"', episode_data)

                        # Przyjmujemy kolejność FHD > HD > SD
                        qualities = {'FHD': None, 'HD': None, 'SD': None}

                        for stream_data in streams_data:
                            quality, value = stream_data
                            if qualities[quality] is None:
                                qualities[quality] = value

                        # Wybieramy najwyższą jakość
                        highest_quality = None
                        if qualities['FHD']:
                            highest_quality = {"url": qualities['FHD'], 'quality': 1080}
                        elif qualities['HD']:
                            highest_quality = {"url": qualities['HD'], 'quality': 720}
                        elif qualities['SD']:
                            highest_quality = {"url": qualities['SD'], 'quality': 480}
                        if match:
                            episode_id = match.group(1)
                            video_links = await fetch_and_decode_video(session, episode_id, is_secondary=False)
                            if not video_links:
                                video_link = await fetch_and_decode_video(session, highest_quality['url'], is_secondary=True)
                                return video_link, highest_quality['quality']
                            else:
                                return get_highest_quality(video_links)

        return None
    except Exception as e:
        logging.error(response.text)
        pass
        return None
