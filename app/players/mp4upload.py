import re
import aiohttp


from app.routes.utils import get_random_agent

async def get_video_from_mp4upload_player(player_url: str):

    try:
        headers = {
            "User-Agent": get_random_agent(),
            "Referer": "https://www.mp4upload.com/"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(player_url, headers=headers, timeout=15) as response:
                response.raise_for_status()
                html_content = await response.text()

            stream_url_match = re.search(r'player\.src\(\s*{\s*type:\s*"video/mp4",\s*src:\s*"([^"]+)"', html_content)

            if not stream_url_match:
                print("MP4Upload Player Error: No video")
                return None, None, None

            stream_url = stream_url_match.group(1)

            quality = "unknown"
            height_match = re.search(r"embed:\s*'[^']*?\bHEIGHT=(\d+)", html_content)
            if height_match:
                height = height_match.group(1)
                quality = f"{height}p"

            stream_headers = {'request': headers}

            return stream_url, quality, stream_headers

    except Exception as e:
        print(f"MP4Upload Player Error: Unexpected Error: {e}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://www.mp4upload.com/embed-4kz23r0tp9li.html",
    ]

    run_tests(get_video_from_mp4upload_player, urls_to_test)