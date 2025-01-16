import aiohttp
from urllib.parse import urlparse, parse_qs

DAILYMOTION_URL = "https://www.dailymotion.com"


async def get_video_from_dailymotion_player(url: str) -> tuple:
    if '/embed/' not in url:
        url = url.replace('/video/', '/embed/video/')
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            response.raise_for_status()
            html_string = await response.text()
        try:
            internal_data_start = html_string.find("\"dmInternalData\":") + len("\"dmInternalData\":")
            internal_data_end = html_string.find("</script>", internal_data_start)
            internal_data = html_string[internal_data_start:internal_data_end]

            ts = internal_data.split("\"ts\":", 1)[1].split(",", 1)[0].strip()
            v1st = internal_data.split("\"v1st\":\"", 1)[1].split("\",", 1)[0].strip()

            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            video_query = query_params.get("video", [None])[0] or parsed_url.path.split("/")[-1]

            json_url = (
                f"{DAILYMOTION_URL}/player/metadata/video/{video_query}"
                f"?locale=en-US&dmV1st={v1st}&dmTs={ts}&is_native_app=0"
            )

            async with session.get(json_url) as metadata_response:
                metadata_response.raise_for_status()
                parsed = await metadata_response.json()

            if "qualities" in parsed and "error" not in parsed:
                return await videos_from_daily_response(parsed)
            else:
                return None, None, None
        except:
            return None, None, None


async def fetch_m3u8_url(master_url: str, headers: dict) -> tuple:
    async with aiohttp.ClientSession() as session:
        async with session.get(master_url, headers=headers) as response:
            response.raise_for_status()
            m3u8_content = await response.text()

    streams = []
    lines = m3u8_content.splitlines()

    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            quality = None
            for part in line.split(","):
                if "NAME" in part:
                    quality = part.split("=")[1].strip("\"")

            if quality:
                stream_url = lines[i + 1]
                streams.append((quality, stream_url))

    if streams:
        best_stream = max(streams, key=lambda x: int(x[0]))
        return best_stream[1], best_stream[0]
    else:
        return None, None


async def videos_from_daily_response(parsed: dict) -> tuple:
    master_url = next(
        (quality.get("url") for quality in parsed.get("qualities", {}).get("auto", []) if "url" in quality),
        None
    )
    if not master_url:
        return None, None, None

    master_headers = headers_builder()
    best_url, best_quality = await fetch_m3u8_url(master_url, master_headers)

    return best_url, f"{best_quality}p", master_headers


def headers_builder() -> dict:
    headers = {
        "Accept": "*/*",
        "Referer": f"{DAILYMOTION_URL}/",
        "Origin": DAILYMOTION_URL
    }

    return headers
