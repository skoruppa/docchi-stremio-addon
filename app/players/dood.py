import re
import logging
import cloudscraper
import asyncio
from concurrent.futures import ThreadPoolExecutor
from app.routes.utils import get_random_agent


class CloudscraperSession:
    def __init__(self):
        self.session = cloudscraper.create_scraper(browser={
            "browser": "chrome",
            "platform": "windows",
        })

    def fetch(self, url, method="GET", **kwargs):
        if method.upper() == "GET":
            return self.session.get(url, **kwargs)
        elif method.upper() == "POST":
            return self.session.post(url, **kwargs)
        else:
            raise ValueError(f"Unsupported method: {method}")


async def fetch_url_async(session, url, method="GET", **kwargs):
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        # Użycie funkcji lambda, aby przekazać `**kwargs`
        return await loop.run_in_executor(
            executor,
            lambda: session.fetch(url, method, **kwargs)
        )


async def get_video_from_dood_player(url):
    quality = "unknown"
    stream_headers = {"request": {"Referer": url}}
    user_agent = get_random_agent()
    headers = {"User-Agent": user_agent}

    session = CloudscraperSession()
    dood_host = re.search(r"https://(.*?)/", url).group(1)

    try:

        response = await fetch_url_async(session, url, "GET", headers=headers)
        content = response.text
        logging.info(content)
        if "'/pass_md5/" not in content:
            return None, None, None

        md5 = content.split("'/pass_md5/")[1].split("',")[0]

        video_response = await fetch_url_async(session,
                f"https://{dood_host}/pass_md5/{md5}", "GET",
                headers={"Referer": url,
                         "User-Agent": user_agent})
        video_url = video_response.text

        return video_url, quality, stream_headers
    except Exception as e:
        logging.error(f"Error: {e}")
        return None, None, None
