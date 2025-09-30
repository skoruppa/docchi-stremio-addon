import base64
import re
import aiohttp
import json
from urllib.parse import urlparse
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from app.routes.utils import get_random_agent
from app.players.utils import fetch_resolution_from_m3u8


async def get_video_from_streamup_player(player_url: str):
    try:
        async with aiohttp.ClientSession() as session:
            user_agent = get_random_agent()
            page_headers = {"User-Agent": user_agent}
            async with session.get(player_url, headers=page_headers, timeout=15) as page_response:
                page_response.raise_for_status()
                page_content = await page_response.text()

            session_id_match = re.search(r"['\"]([a-f0-9]{32})['\"]", page_content)
            encrypted_data_match = re.search(r"['\"]([A-Za-z0-9+/=]{200,})['\"]", page_content)

            if not encrypted_data_match or not session_id_match:
                print("Error StreamUP: could not find 'encrypted data' or 'session id'")
                return None, None, None

            session_id = session_id_match.group(1)
            encrypted_data_b64 = encrypted_data_match.group(1)

            parsed_url = urlparse(str(page_response.url))
            base_url_with_scheme = f"{parsed_url.scheme}://{parsed_url.netloc}"

            key_url = f"{base_url_with_scheme}/ajax/stream?session={session_id}"
            key_headers = {"User-Agent": user_agent, "Referer": player_url}

            async with session.get(key_url, headers=key_headers, timeout=15) as key_response:
                key_response.raise_for_status()
                key_b64 = await key_response.text()

            key = base64.b64decode(key_b64)

            encrypted_data = base64.b64decode(encrypted_data_b64)
            iv = encrypted_data[:16]
            ciphertext = encrypted_data[16:]

            cipher = AES.new(key, AES.MODE_CBC, iv)
            decrypted_padded = cipher.decrypt(ciphertext)
            decrypted_data_str = unpad(decrypted_padded, AES.block_size).decode('utf-8')

            stream_info = json.loads(decrypted_data_str)
            stream_url = stream_info.get("streaming_url")

            if not stream_url:
                print("Error StreamUP: 'streaming_url' not found.")
                return None, None, None

            stream_headers_dict = {
                "User-Agent": user_agent,
                "Referer": base_url_with_scheme + "/",
                "Origin": base_url_with_scheme
            }
            stream_headers = {'request': stream_headers_dict}

            quality = await fetch_resolution_from_m3u8(session, stream_url, stream_headers_dict) or "unknown"

            return stream_url, quality, stream_headers

    except Exception as e:
        print(f"StreamUP Player Error: Unexpected Error: {e}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests
    urls_to_test = [
        "https://strmup.to/rhNq4BtUoJvsi"
    ]

    run_tests(get_video_from_streamup_player, urls_to_test)