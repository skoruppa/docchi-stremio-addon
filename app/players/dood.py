import re
import logging

import httpx

from app.routes.utils import get_random_agent


class HttpxSession:
    def __init__(self):
        self.client = httpx.AsyncClient(http2=True, follow_redirects=True)  # Obsługa HTTP/2 (opcjonalna)

    async def fetch(self, url, method="GET", **kwargs):
        if method.upper() == "GET":
            response = await self.client.get(url, **kwargs)
        elif method.upper() == "POST":
            response = await self.client.post(url, **kwargs)
        else:
            raise ValueError(f"Unsupported method: {method}")

        response.raise_for_status()  # Rzuć wyjątek, jeśli kod HTTP jest błędny
        return response

    async def close(self):
        await self.client.aclose()


async def get_video_from_dood_player(url):
    quality = "unknown"
    stream_headers = {"request": {"Referer": url}}
    user_agent = get_random_agent()
    headers = {"User-Agent": user_agent}

    session = HttpxSession()

    dood_host = re.search(r"https://(.*?)/", url).group(1)

    try:

        response = await session.fetch(url, "GET", headers=headers)
        content = response.text
        logging.info(content)
        if "'/pass_md5/" not in content:
            return None, None, None

        md5 = content.split("'/pass_md5/")[1].split("',")[0]

        video_response = await session.fetch(
                f"https://{dood_host}/pass_md5/{md5}", "GET",
                headers={"Referer": url,
                         "User-Agent": user_agent})
        video_url = video_response.text

        return video_url, quality, stream_headers
    except Exception as e:
        logging.error(f"Error: {e}")
        return None, None, None
