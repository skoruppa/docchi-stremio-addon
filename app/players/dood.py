import re
import time
import string
import random
import cloudscraper
from urllib.parse import urlparse

DOMAINS = [
    'dood.watch', 'doodstream.com', 'dood.to', 'dood.so', 'dood.cx', 'dood.la', 'dood.ws',
    'dood.sh', 'doodstream.co', 'dood.pm', 'dood.wf', 'dood.re', 'dood.yt', 'dooood.com',
    'dood.stream', 'ds2play.com', 'doods.pro', 'ds2video.com', 'd0o0d.com', 'do0od.com',
    'd0000d.com', 'd000d.com', 'dood.li', 'dood.work', 'dooodster.com', 'vidply.com',
    'all3do.com', 'do7go.com', 'doodcdn.io', 'doply.net', 'vide0.net', 'vvide0.com',
    'd-s.io', 'dsvplay.com', 'myvidplay.com'
]

ENABLED = True
# cloudflare blocks requests from vercel. Works locally even without cloudscraper

async def get_video_from_dood_player(session, player_url, is_vip: bool = False):
    """Extract video URL from DoodStream player"""
    
    parsed = urlparse(player_url)
    video_id = parsed.path.rstrip('/').split('/')[-1]
    
    # Normalize to /e/ endpoint
    url = f"http://dood.to/e/{video_id}"
    print(f"Dood Player: Processing URL: {url}")
    
    try:
        # Use cloudscraper to bypass Cloudflare
        print("Dood Player: Creating cloudscraper instance...")
        scraper = cloudscraper.create_scraper(
            enable_stealth=True,
            stealth_options={
                'min_delay': 2.0,
                'max_delay': 3.0,
                'human_like_delays': True,
                'randomize_headers': True,
                'browser_quirks': True
            },

            # Browser emulation
            browser='chrome',

            # Debug mode
            debug=False
        )
        
        print(f"Dood Player: Fetching page: {url}")
        response = scraper.get(url)
        print(f"Dood Player: Response status: {response.status_code}")
        html = response.text
        print(f"Dood Player: HTML length: {len(html)}")
        
        if 'Video not found' in html:
            print("Dood Player Error: Video not found")
            return None, None, None
        
        # Extract pass_md5 path and token
        pass_md5_match = re.search(r'/pass_md5/[\w-]+/([\w-]+)', html)
        if not pass_md5_match:
            print("Dood Player Error: No pass_md5 match found")
            return None, None, None
        
        token = pass_md5_match.group(1)
        pass_md5_url = f"http://dood.to{pass_md5_match.group(0)}"
        print(f"Dood Player: Token: {token}")
        print(f"Dood Player: Fetching pass_md5: {pass_md5_url}")
        
        # Get base URL using cloudscraper
        pass_response = scraper.get(pass_md5_url, headers={'Referer': url})
        print(f"Dood Player: pass_md5 response status: {pass_response.status_code}")
        base_url = pass_response.text.strip()
        print(f"Dood Player: Base URL: {base_url}")
        
        # Build final URL
        if 'cloudflarestorage' in base_url:
            final_url = base_url
            print("Dood Player: Using cloudflare storage URL")
        else:
            random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
            expiry = int(time.time() * 1000)
            final_url = f"{base_url}{random_str}?token={token}&expiry={expiry}"
            print(f"Dood Player: Built final URL with random string")
        
        print(f"Dood Player: Success - Final URL: {final_url[:100]}...")
        stream_headers = {'request': {'Referer': 'http://dood.to'}}
        return final_url, 'unknown', stream_headers
    
    except Exception as e:
        print(f"Dood Player Error: Unexpected Error: {e}")
        return None, None, None


if __name__ == '__main__':
    from app.players.test import run_tests

    urls_to_test = [
        "https://dood.yt/e/aorzlvboafi6"
    ]

    run_tests(get_video_from_dood_player, urls_to_test)