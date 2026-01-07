import re
import aiohttp
import json
from app.utils.common_utils import get_random_agent
from app.utils.common_utils import fetch_resolution_from_m3u8

# Domains handled by this player
DOMAINS = ['rumble.com']


def extract_ua_section(js_string):
    try:
        ua_start = js_string.find('"ua":')
        if ua_start == -1:
            raise ValueError("Section 'ua' not found")

        brace_start = js_string.find('{', ua_start)
        if brace_start == -1:
            raise ValueError("Opening brace not found")

        brace_count = 0
        current_pos = brace_start

        while current_pos < len(js_string):
            char = js_string[current_pos]
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    ua_object = js_string[brace_start:current_pos + 1]
                    break
            current_pos += 1
        else:
            raise ValueError("Closing brace not found")

        ua_json = '{"ua":' + ua_object + '}'

        parsed = json.loads(ua_json)

        return parsed

    except Exception as e:
        print(f"Error during processing: {e}")
        return None


async def get_video_from_rumble_player(session: aiohttp.ClientSession, url):
    headers = {
        "User-Agent": get_random_agent()
    }

    final_url = url

    if "/embed/" not in url:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                print(f"Error fetching page {url}: Status {response.status}")
                return None, None, None
            page_text = await response.text()

            script_pattern = re.compile(r'<script type=application/ld\+json>(.*?)</script>', re.DOTALL)
            script_match = script_pattern.search(page_text)

            if script_match:
                try:
                    json_ld_content = script_match.group(1)
                    data_array = json.loads(json_ld_content)
                    for item in data_array:
                        if item.get('@type') == 'VideoObject' and 'embedUrl' in item:
                            final_url = item['embedUrl']
                            print(f"Found embedUrl: {final_url}")
                            break
                    else:
                        print("No 'embedUrl' found in 'VideoObject' in JSON-LD.")
                        return None, None, None
                except json.JSONDecodeError as e:
                    print(f"JSON-LD decoding error: {e}")
                    return None, None, None
            else:
                print("JSON-LD script not found on the page.")
                return None, None, None

    async with session.get(final_url, headers=headers) as response:
        if response.status != 200:
            print(f"Error fetching final_url {final_url}: Status {response.status}")
            return None, None, None

        text = await response.text()

    json_pattern = re.compile(r'"ua":\{.*?\}\}\}\}', re.DOTALL)
    match = json_pattern.search(text)

    if not match:
        print(f"No matching JSON pattern 'ua' found for URL: {final_url}")
        return None, None, None

    json_str = '{' + match.group(0) + '}'
    data = extract_ua_section(json_str)

    if data is None:
        print(f"Failed to process 'ua' section for URL: {final_url}")
        return None, None, None

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
        print(f"No video data found in sources for URL: {final_url}")
        return None, None, None

    if 'auto' in video_data:
        highest_resolution = 'auto'
    else:
        highest_resolution = max(video_data.keys(), key=lambda res: int(res))

    highest_quality_url = video_data[highest_resolution]['url'].replace('\\/', '/')

    highest_quality_url += highest_quality_url_string
    if highest_resolution == 'auto':
        highest_resolution = await fetch_resolution_from_m3u8(session, highest_quality_url,
                                                              stream_headers['request'])
    else:
        highest_resolution = f"{highest_resolution}p"

    return highest_quality_url, highest_resolution, stream_headers

if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://rumble.com/v716bwo-frixttwakrnin05.html"
    ]

    run_tests(get_video_from_rumble_player, urls_to_test)


