import re
import logging
import aiohttp
import time
import string
import random
from app.utils.common_utils import get_random_agent
from flask import request

# Domains handled by this player
DOMAINS = ['dood.stream', 'dood.watch', 'dood.to', 'dood.so', 'dood.pm']

# NOTE: Disabled - can't bypass Cloudflare protection on remote server
ENABLED = False


async def get_video_from_dood_player(session: aiohttp.ClientSession, url):
    user_agent = request.headers.get('User-Agent', get_random_agent())
    quality = "unknown"

    dood_host = re.search(r"https://(.*?)/", url).group(1)

    try:
        async with session.get(url, headers={"User-Agent": user_agent}) as response:
            new_url = str(response.url)
            stream_headers = {"request": {"Referer": new_url}}
            content = await response.text()

            logging.info(content)
            print(f"dood: {content}")

            if "'/pass_md5/" not in content:
                return None, None, None

            md5 = content.split("'/pass_md5/")[1].split("',")[0]

            token_url = f"https://{dood_host}/pass_md5/{md5}"
            async with session.get(
                    token_url,
                    headers={"Referer": new_url, "User-Agent": user_agent}
            ) as token_response:
                token = await token_response.text()

            random_string = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
            expiry = int(time.time() * 1000)
            final_url = f"{token}{random_string}?token={md5}&expiry={expiry}"
            
            return final_url, quality, stream_headers

    except Exception as e:
        logging.error(f"Error: {e}")
        return None, None, None