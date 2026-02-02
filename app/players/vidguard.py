import re
import json
import asyncio
import aiohttp
import sys
import base64
from urllib.parse import urlparse, parse_qs, urlencode
from py_mini_racer import MiniRacer

from app.utils.common_utils import get_random_agent
from app.utils.common_utils import fetch_resolution_from_m3u8

# NOTE: Disabled - seems to be down right now
DOMAINS = ['listeamed.net', 'vidguard.to', 'vgfplay.com']
ENABLED = False

sys.setrecursionlimit(2000)



def _decode_e(hex_string: str, key: int) -> str:
    result = ""
    for i in range(0, len(hex_string), 2):
        hex_byte = hex_string[i:i + 2]
        int_byte = int(hex_byte, 16)
        xored_byte = int_byte ^ key
        result += chr(xored_byte)
    return result


def _decode_f(s: str) -> str:
    reversed_s = s[::-1]
    char_list = list(reversed_s)
    for i in range(0, len(char_list) - 1, 2):
        char_list[i], char_list[i + 1] = char_list[i + 1], char_list[i]
    return "".join(char_list)


def _decode_player_and_get_stream(script_content: str) -> str | None:
    try:
        ctx = MiniRacer()
        ctx.eval("var window = {};")
        ctx.eval(script_content)
        svg_object_json_string = ctx.eval("JSON.stringify(window.svg)")
        if not svg_object_json_string:
            print("VidGuard Player Error: 'window.svg' object not found after JS execution.")
            return None
        svg_object = json.loads(svg_object_json_string)
        if svg_object and isinstance(svg_object, dict) and 'stream' in svg_object:
            return svg_object['stream']
        print("VidGuard Player Error: 'stream' key not found in 'window.svg' object.")
        return None
    except Exception as e:
        print(f"VidGuard Player Error: An exception occurred during JS execution: {e}")
        return None


async def get_video_from_vidguard_player(session: aiohttp.ClientSession, player_url: str, is_vip: bool = False):
    loop = asyncio.get_running_loop()
    try:
        parsed_url = urlparse(player_url)
        origin = f"{parsed_url.scheme}://{parsed_url.netloc}"

        headers = {
            "User-Agent": get_random_agent(),
            "Referer": origin + '/',
            "Origin": origin,
        }

        async with session.get(player_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            html_content = await response.text()

        script_content = None
        script_blocks = re.findall(r"<script[^>]*>(.*?)</script>", html_content, re.DOTALL)

        for block in script_blocks:
            if 'ﾟωﾟ' in block:
                script_content = block.strip()
                break

        if not script_content:
            print("VidGuard Player Error: Could not find the obfuscated script containing 'ﾟωﾟ'.")
            return None, None, None

        raw_stream_url = await loop.run_in_executor(None, _decode_player_and_get_stream, script_content)

        if not raw_stream_url:
            print("VidGuard Player Error: Failed to decode stream URL from script.")
            return None, None, None

        parsed_stream_url = urlparse(raw_stream_url)
        query_params = parse_qs(parsed_stream_url.query)

        if 'sig' in query_params:
            original_sig = query_params['sig'][0]

            step1 = _decode_e(original_sig, 2)


            padding_needed = len(step1) % 4
            if padding_needed:
                step1 += '=' * (4 - padding_needed)

            try:
                step2 = base64.b64decode(step1).decode('utf-8')
            except Exception as e:
                print(f"VidGuard Base64 Decode Error: {e}")
                return None, None, None

            if len(step2) < 10:
                print(f"VidGuard Error: Decoded string is too short: {step2}")
                return None, None, None

            trimmed = step2[5:-5]
            new_sig = _decode_f(trimmed)

            query_params['sig'] = [new_sig]
            new_query = urlencode(query_params, doseq=True)
            final_stream_url = parsed_stream_url._replace(query=new_query).geturl()
        else:
            final_stream_url = raw_stream_url

        stream_headers = {'request': headers}

        quality = "unknown"
        try:
            fetched_quality = await fetch_resolution_from_m3u8(session, final_stream_url, headers)
            if fetched_quality:
                quality = fetched_quality
        except Exception as e:
            print(f"VidGuard Info: Could not fetch resolution. Reason: {e}")

        return final_stream_url, quality, stream_headers

    except Exception as e:
        print(f"VidGuard Player Error: Unexpected error: {e}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://listeamed.net/e/JzkPxzX4NpAObyd"
    ]

    run_tests(get_video_from_vidguard_player, urls_to_test)