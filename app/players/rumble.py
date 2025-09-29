import re
import aiohttp
import json
from app.routes.utils import get_random_agent


def extract_ua_section(js_string):
    try:
        # Znajdź początek obiektu ua
        ua_start = js_string.find('"ua":')
        if ua_start == -1:
            raise ValueError("Nie znaleziono sekcji 'ua'")

        # Rozpocznij od pierwszego {
        brace_start = js_string.find('{', ua_start)
        if brace_start == -1:
            raise ValueError("Nie znaleziono otwierającego nawiasu klamrowego")

        # Znajdź odpowiadający zamykający nawias klamrowy
        brace_count = 0
        current_pos = brace_start

        while current_pos < len(js_string):
            char = js_string[current_pos]
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    # Znaleźliśmy koniec obiektu ua
                    ua_object = js_string[brace_start:current_pos + 1]
                    break
            current_pos += 1
        else:
            raise ValueError("Nie znaleziono zamykającego nawiasu klamrowego")

        # Stwórz kompletny JSON z sekcją ua
        ua_json = '{"ua":' + ua_object + '}'

        # Sprawdź czy JSON jest poprawny
        parsed = json.loads(ua_json)

        return parsed

    except Exception as e:
        print(f"Błąd podczas przetwarzania: {e}")
        return None, None


async def get_video_from_rumble_player(url):
    headers = {
        "User-Agent": get_random_agent()
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                return None, None, None

            text = await response.text()

    json_pattern = re.compile(r'"ua":\{.*?\}\}\}\}', re.DOTALL)
    match = json_pattern.search(text)

    if not match:
        return None, None, None

    json_str = '{' + match.group(0) + '}'
    data = extract_ua_section(json_str)
    stream_headers = {
        'request': {
            "Origin": "https://rumble.com/",
            "Referer": "https://rumble.com/",
            "User-Agent": headers['User-Agent']
        }
    }
    video_sources = data.get('ua', {})

    highest_quality_url_string = ""
    video_data = None
    if 'mp4' in video_sources and video_sources['mp4']:
        video_data = video_sources['mp4']
        highest_quality_url_string = "?u=0&b=0"
        stream_headers['request']["Range"] = "bytes=0-"
        stream_headers['request']["Priority"] = "u=4"
    elif 'hls' in video_sources and video_sources['hls']:
        video_data = video_sources['hls']
    elif 'tar' in video_sources and video_sources['tar']:
        video_data = video_sources['tar']

    if not video_data:
        return None, None, None

    if 'auto' in video_data:
        highest_resolution = 'auto'
    else:
        highest_resolution = max(video_data.keys(), key=lambda res: int(res))

    highest_quality_url = video_data[highest_resolution]['url'].replace('\\/', '/')

    highest_quality_url += highest_quality_url_string



    return highest_quality_url, f"{highest_resolution}p", stream_headers