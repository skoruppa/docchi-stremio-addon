import re
import aiohttp


async def get_video_from_dood_player(url):
    quality = "unknown"
    stream_headers = {"request": {"Referer": url}}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                dood_host = re.search(r"https://(.*?)/", url).group(1)
                content = await response.text()

                if "'/pass_md5/" not in content:
                    return None, None, None

                md5 = content.split("'/pass_md5/")[1].split("',")[0]

                async with session.get(
                    f"https://{dood_host}/pass_md5/{md5}",
                    headers={"Referer": url}
                ) as video_response:
                    video_url = await video_response.text()

                return video_url, quality, stream_headers
    except Exception as e:
        print(f"Error: {e}")
        return None, None, None