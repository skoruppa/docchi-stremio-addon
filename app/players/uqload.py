import re
from bs4 import BeautifulSoup
import aiohttp
from config import Config

PROXIFY_CDA = Config.PROXIFY_CDA
CDA_PROXY_URL = Config.CDA_PROXY_URL
CDA_PROXY_PASSWORD = Config.CDA_PROXY_PASSWORD


async def get_video_from_uqload_player(url: str):

    if PROXIFY_CDA:
        url = f'{CDA_PROXY_URL}/proxy/stream?d={url}&api_password={CDA_PROXY_PASSWORD}'

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            text = await response.text()

    soup = BeautifulSoup(text, 'html.parser')
    script_tags = soup.find_all('script')

    headers = {"request": {"Referer": "https://uqload.co/"}}
    quality = "unknown"

    for script in script_tags:
        if script.string and 'sources:' in script.string:
            match = re.search(r'sources:\s*\["(https?.*?\.mp4)"\]', script.string)
            if match:
                stream_url = match.group(1)
                if PROXIFY_CDA:
                    post_data = {
                        "mediaflow_proxy_url": CDA_PROXY_URL,
                        "endpoint": "/proxy/stream",
                        "destination_url": stream_url,
                        "expiration": 7200,
                        "api_password": CDA_PROXY_PASSWORD,
                    }
                    async with session.post(f'{CDA_PROXY_URL}/generate_encrypted_or_encoded_url',
                                            json=post_data) as response:
                        response.raise_for_status()
                        result = await response.json()
                    stream_url = result.get("encoded_url", {})
                return stream_url, quality, headers

    return None, None, None
