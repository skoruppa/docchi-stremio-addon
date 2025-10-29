import logging
import random
from flask import jsonify, flash, make_response, url_for, redirect, Response, request
from flask_caching import Cache
import json
import hashlib
cache = Cache()


def handle_error(err) -> Response:
    """
    Handles errors from MyAnimeList's API
    """
    if 400 >= err.response.status_code < 500:
        flash(err, "danger")
        return make_response(redirect(url_for('index')))
    elif err.response.status_code >= 500:
        log_error(err)
        flash(err, "danger")
        return make_response(redirect(url_for('index')))


def log_error(err):
    """
    Logs errors from MyAnimeList's API
    """
    if hasattr(err, 'response') and err.response is not None:
        try:
            response = err.response.json()
            error_label = response.get('error', 'No error label in response').capitalize()
            message = response.get('message', 'No message field in response')
            hint = response.get('hint', 'No hint field in response')
            status_code = err.response.status_code
            logging.error(f"{error_label} [{status_code}] -> {message}\n HINT: {hint}\n")
        except json.JSONDecodeError:
            status_code = err.response.status_code
            logging.error(f"API Error [{status_code}] -> Response is not in JSON format:\n{err.response.text}\n")
        except Exception as e:
            logging.error(f"An unexpected error occurred while processing the API response: {e}\n")
    else:
        logging.error(f"An unexpected error occurred: {err}\n")


def generate_etag(data: dict) -> str:
    data_str = json.dumps(data, sort_keys=True)
    return hashlib.md5(data_str.encode()).hexdigest()


# Enable CORS
def respond_with(data: dict, cache_time: int = None, client_cache_time: int = 0) -> Response:
    """
    Respond with CORS headers to the client
    """
    #    etag = generate_etag(data)

    #    if request.headers.get('If-None-Match') == etag:
    #        return Response(status=304)

    resp = jsonify(data)
    if cache_time:
        resp.headers['Cache-Control'] = f'public, s-max-age={cache_time}, max-age={client_cache_time}'
        resp.headers['CDN-Cache-Control'] = f'public, s-maxage={cache_time}, maxage={cache_time}'
        resp.headers['Vercel-CDN-Cache-Control'] = f'public, s-maxage={cache_time}'
        resp.headers['Cloudflare-CDN-Cache-Control'] = f'public, maxage={cache_time}'
    #    resp.headers['ETag'] = etag
    resp.headers['Access-Control-Allow-Origin'] = "*"
    resp.headers['Access-Control-Allow-Headers'] = '*'
    return resp


def get_random_agent(browser: str = None):
    USER_AGENTS_BY_BROWSER = {
        "chrome": [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
        ],
        "firefox": [
            "Mozilla/5.0 (X11; Linux x86_64; rv:143.0) Gecko/20100101 Firefox/143.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/119.0",
        ],
        "safari": [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
        ],
        "opera": [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 OPR/104.0.0.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 OPR/104.0.0.0",
        ]
    }

    if browser:
        if browser.lower() in USER_AGENTS_BY_BROWSER:
            return random.choice(USER_AGENTS_BY_BROWSER[browser.lower()])

    all_agents = [agent for sublist in USER_AGENTS_BY_BROWSER.values() for agent in sublist]
    return random.choice(all_agents)
