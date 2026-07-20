"""
Stream and routing utilities for FastAPI responses.
"""

import logging
import json
import hashlib
from fastapi.responses import JSONResponse


def handle_error(err):
    """Handles errors from MyAnimeList's API"""
    log_error(err)


def log_error(err):
    """Logs errors from API calls"""
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


def log_warning(err):
    """Logs warnings from API calls"""
    if hasattr(err, 'response') and err.response is not None:
        try:
            response = err.response.json()
            error_label = response.get('error', 'No error label in response').capitalize()
            message = response.get('message', 'No message field in response')
            hint = response.get('hint', 'No hint field in response')
            status_code = err.response.status_code
            logging.warning(f"{error_label} [{status_code}] -> {message}\n HINT: {hint}\n")
        except json.JSONDecodeError:
            status_code = err.response.status_code
            logging.warning(f"API Warning [{status_code}] -> Response is not in JSON format:\n{err.response.text}\n")
        except Exception as e:
            logging.warning(f"An unexpected error occurred while processing the API response: {e}\n")
    else:
        logging.warning(f"An unexpected warning occurred: {err}\n")


def generate_etag(data: dict) -> str:
    """Generate ETag for response data"""
    data_str = json.dumps(data, sort_keys=True)
    return hashlib.md5(data_str.encode()).hexdigest()


def respond_with(data: dict, cache_time: int = None) -> JSONResponse:
    """Respond with CORS headers to the client"""
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': '*',
    }
    if cache_time:
        headers['Cache-Control'] = f'public, s-maxage={cache_time}, max-age={cache_time}, stale-while-revalidate=60'
        headers['CDN-Cache-Control'] = f'public, s-maxage={cache_time}, stale-while-revalidate=60'
        headers['Vercel-CDN-Cache-Control'] = f'public, s-maxage={cache_time}, stale-while-revalidate=60'
        headers['Cloudflare-CDN-Cache-Control'] = f'public, max-age={cache_time}, stale-while-revalidate=60'
    return JSONResponse(content=data, headers=headers)
