import re
import logging
import aiohttp
from app.routes.utils import get_random_agent
from config import Config
from flask import request

PROXIFY_CDA = Config.PROXIFY_CDA
CDA_PROXY_URL = Config.CDA_PROXY_URL
CDA_PROXY_PASSWORD = Config.CDA_PROXY_PASSWORD


async def get_video_from_dood_player(url):
    user_agent = request.headers.get('User-Agent', get_random_agent())
    quality = "unknown"

    dood_host = re.search(r"https://(.*?)/", url).group(1)

    if PROXIFY_CDA:
        url = f'{CDA_PROXY_URL}/proxy/stream?d={url}&api_password={CDA_PROXY_PASSWORD}'

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers={"User-Agent": user_agent}) as response:
                new_url = str(response.url)
                stream_headers = {"request": {"Referer": new_url}}
                content = await response.text()

                logging.info(content)
                print(f"dood: {content}")

                if "'/pass_md5/" not in content:
                    return None, None, None

                md5 = content.split("'/pass_md5/")[1].split("',")[0]

                video_url = f"https://{dood_host}/pass_md5/{md5}"
                async with session.get(
                        video_url,
                        headers={"Referer": new_url, "User-Agent": user_agent}
                ) as video_response:
                    video_content = await video_response.text()
                    return video_content, quality, stream_headers

    except Exception as e:
        logging.error(f"Error: {e}")
        return None, None, None