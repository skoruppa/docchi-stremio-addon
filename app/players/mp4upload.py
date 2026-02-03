import re
import aiohttp


from app.utils.common_utils import get_random_agent

# Domains handled by this player
DOMAINS = ['mp4upload.com']
NAMES = ['mp4upload']

async def get_video_from_mp4upload_player(session: aiohttp.ClientSession, player_url: str, is_vip: bool = False):

    try:
        headers = {
            "User-Agent": get_random_agent(),
            "Referer": "https://www.mp4upload.com/"
        }

        async with session.get(player_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
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