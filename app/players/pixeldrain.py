import re
import aiohttp
from urllib.parse import urlparse

from app.routes.utils import get_random_agent
from config import Config


PROXIFY_STREAMS = Config.PROXIFY_STREAMS
STREAM_PROXY_URL = Config.STREAM_PROXY_URL
STREAM_PROXY_PASSWORD = Config.STREAM_PROXY_PASSWORD

async def get_video_from_pixeldrain_player(player_url: str):
    user_agent = get_random_agent()
    headers = {"User-Agent": user_agent}

    try:
        parsed_url = urlparse(player_url)
        path = parsed_url.path

        # Regex to capture the type (u, l, file) and the ID
        match = re.search(r'/(u|l|file)/([0-9a-zA-Z\-]+)', path)
        if not match:
            print(f"PixelDrain Error: Invalid URL format for {player_url}")
            return None, None, None

        mtype, mid = match.groups()

        stream_url = None

        # If it's a list link, we need to fetch the list and find the video
        if mtype == 'l':
            api_url = f"https://pixeldrain.com/api/list/{mid}"
            if PROXIFY_STREAMS:
                api_url = f'{STREAM_PROXY_URL}/proxy/stream?d={api_url}&api_password={STREAM_PROXY_PASSWORD}&h_user-agent={user_agent}'
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(verify_ssl=False)) as session:
                async with session.get(api_url, headers=headers) as response:
                    response.raise_for_status()
                    data = await response.json()

            if not data.get('success'):
                error_message = data.get('message', 'Unknown API error')
                print(f"PixelDrain API Error for list {mid}: {error_message}")
                return None, None, None

            # Filter for video files and select the largest one
            video_files = [f for f in data.get('files', []) if f.get('mime_type') and 'video' in f['mime_type']]
            if not video_files:
                print(f"PixelDrain Error: No video files found in list {mid}.")
                return None, None, None

            largest_video = max(video_files, key=lambda x: x.get('size', 0))
            file_id = largest_video.get('id')
            if not file_id:
                print("PixelDrain Error: Could not determine file ID from the largest video.")
                return None, None, None

            stream_url = f"https://pixeldrain.com/api/file/{file_id}"

        # If it's a single file link (u or file), the URL can be constructed directly
        elif mtype in ('u', 'file'):
            stream_url = f"https://pixeldrain.com/api/file/{mid}"

        if stream_url:
            # PixelDrain doesn't typically require special headers for playback
            stream_headers = {'request': headers}
            quality = "unknown"

            return stream_url, quality, stream_headers

    except aiohttp.ClientError as http_err:
        print(f"PixelDrain Player Error: An HTTP error occurred: {http_err}")
        return None, None, None
    except Exception as e:
        print(f"PixelDrain Player Error: An unexpected error occurred: {e}")
        return None, None, None

    # Fallback return
    return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://pixeldrain.com/u/rkHjhTWZ?embed"
    ]

    run_tests(get_video_from_pixeldrain_player, urls_to_test)