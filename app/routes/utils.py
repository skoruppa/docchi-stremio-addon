import logging
import random
from flask import jsonify, flash, make_response, url_for, redirect, Response, request
from flask_caching import Cache
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
    response = err.response.json()
    error_label = response.get('error', 'No error label in response').capitalize()
    message = response.get('message', 'No message field in response')
    hint = response.get('hint', 'No hint field in response')
    logging.error(f"{error_label} [{err.response.status_code}] -> {message}\n HINT: {hint}\n")


def generate_etag(data):
    return hashlib.md5(data.encode()).hexdigest()


# Enable CORS
def respond_with(data) -> Response:
    """
    Respond with CORS headers to the client
    """
    etag = generate_etag(data)

    if request.headers.get('If-None-Match') == etag:
        return Response(status=304)

    resp = jsonify(data)
    resp.headers['Cache-Control'] = 'public, s-max-age=600'
    resp.headers['ETag'] = etag
    resp.headers['Access-Control-Allow-Origin'] = "*"
    resp.headers['Access-Control-Allow-Headers'] = '*'
    return resp


def get_random_agent() -> str:
    """Get random user agent."""
    USER_AGENTS = [
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            " AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0"
            " Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            " AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0"
            " Safari/537.36"
        ),
        (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like"
            " Gecko) Chrome/108.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            " AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1"
            " Safari/605.1.15"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_1) AppleWebKit/605.1.15"
            " (KHTML, like Gecko) Version/16.1 Safari/605.1.15"
        ),
    ]
    return random.choice(USER_AGENTS)
