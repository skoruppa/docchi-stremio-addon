import re
import aiohttp
import logging
from app.routes.utils import get_random_agent


async def get_video_from_dood_player(url):
    quality = "unknown"
    stream_headers = {"request": {"Referer": url}}
    user_agent = get_random_agent()
    headers = {"User-Agent": user_agent}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                dood_host = re.search(r"https://(.*?)/", url).group(1)

                content = await response.text()
                logging.info(content)
                if "'/pass_md5/" not in content:
                    return None, None, None

                md5 = content.split("'/pass_md5/")[1].split("',")[0]

                async with session.get(
                    f"https://{dood_host}/pass_md5/{md5}",
                    headers={"Referer": url,
                             "User-Agent": user_agent}
                ) as video_response:
                    video_url = await video_response.text()

                return video_url, quality, stream_headers
    except Exception as e:
        logging.error(f"Error: {e}")
        return None, None, None