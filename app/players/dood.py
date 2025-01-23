import re
import logging
import aiohttp
from app.routes.utils import get_random_agent
from flask import request


async def get_video_from_dood_player(url):
    user_agent = request.headers.get('User-Agent', get_random_agent())
    quality = "unknown"

    dood_host = re.search(r"https://(.*?)/", url).group(1)

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