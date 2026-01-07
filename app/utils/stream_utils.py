"""
Stream and routing utilities for Flask responses.
"""

import logging
import json
import hashlib
from flask import jsonify, flash, make_response, url_for, redirect, Response, request
from flask_caching import Cache

cache = Cache()


def handle_error(err) -> Response:
    """Handles errors from MyAnimeList's API"""
    if 400 >= err.response.status_code < 500:
        flash(err, "danger")
        return make_response(redirect(url_for('index')))
    elif err.response.status_code >= 500:
        log_error(err)
        flash(err, "danger")
        return make_response(redirect(url_for('index')))


def log_error(err):
    """Logs errors from MyAnimeList's API"""
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
    """Generate ETag for response data"""
    data_str = json.dumps(data, sort_keys=True)
    return hashlib.md5(data_str.encode()).hexdigest()


def respond_with(data: dict, cache_time: int = None, client_cache_time: int = 0) -> Response:
    """Respond with CORS headers to the client"""
    resp = jsonify(data)
    if cache_time:
        resp.headers['Cache-Control'] = f'public, s-max-age={cache_time}, max-age={client_cache_time}'
        resp.headers['CDN-Cache-Control'] = f'public, s-maxage={cache_time}, maxage={cache_time}'
        resp.headers['Vercel-CDN-Cache-Control'] = f'public, s-maxage={cache_time}'
        resp.headers['Cloudflare-CDN-Cache-Control'] = f'public, maxage={cache_time}'
    resp.headers['Access-Control-Allow-Origin'] = "*"
    resp.headers['Access-Control-Allow-Headers'] = '*'
    return resp
