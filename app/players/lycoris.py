import aiohttp
import base64
import json
from bs4 import BeautifulSoup
import re

GET_SECONDARY_URL = "https://www.lycoris.cafe/api/getSecondaryLink"


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
        return json.loads(base64.b64decode(decoded).decode('utf-8'))
    except Exception as error:
        print(f"Error decoding URL: {error}")
        return None


async def fetch_and_decode(session: aiohttp.ClientSession, episode_id: str):
    try:
        async with session.get(GET_SECONDARY_URL, params={"id": episode_id}) as response:
            response.raise_for_status()
            data = await response.text()
            decoded_url = decode_video_links(data)
            return decoded_url
    except aiohttp.ClientError as e:
        print(f"Error during request: {e}")
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
            async with session.get(url) as response:
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
                        if match:
                            episode_id = match.group(1)
                            video_links = await fetch_and_decode(session, episode_id)
                            if video_links:
                                return get_highest_quality(video_links)

        return None
    except Exception as e:
        print(f"Error: {e}")
        return None
