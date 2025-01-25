import logging
import requests
from urllib.parse import urlencode, quote
from requests import HTTPError
from datetime import datetime
from bs4 import BeautifulSoup
import json

BASE_URL = "https://api.docchi.pl/v1"
TIMEOUT = 30


class DocchiAPI:
    """
    Docchi API wrapper
    """

    def __init__(self):
        """
        Initialize the Docchi API wrapper
        """

    @staticmethod
    def get_anime_details(slug: str):
        """
        Get anime details from Docchi
        :param slug: anime slug
        :return: JSON response
        """

        if slug is None:
            raise Exception("A Valid Anime slug Must Be Provided")

        url = f'{BASE_URL}/series/find/{slug}'

        resp = requests.get(url=url, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def get_episode_players(slug: str, episode: int):
        """
        Get anime details from Docchi
        :param slug: anime slug
        :param episode: episode number
        :return: JSON response
        """

        if episode is None:
            raise Exception("A Valid episode number Must Be Provided")

        try:
            url = f'{BASE_URL}/episodes/find/{slug}/{episode}'

            resp = requests.get(url=url, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError:
            return None

    @staticmethod
    def get_slug_from_mal_id(mal_id: str):
        """
        Get anime details from Docchi
        :param mal_id: anime slug
        :return: slug
        """

        if mal_id is None:
            raise Exception("A Valid mal id Must Be Provided")

        url = f'{BASE_URL}/series/related/{mal_id}'

        resp = requests.get(url=url, timeout=TIMEOUT)
        resp.raise_for_status()
        related_items = resp.json()
        for item in related_items:
            if item['mal_id'] == int(mal_id):
                return item['slug']
        return None

    @staticmethod
    def get_current_season():
        """
        Get current anime season
        :return: tuple of season and season_year
        """

        now = datetime.now()
        current_year = now.year

        # 1 kwietnia zaczyna się wiosna
        if now < datetime(current_year, 4, 1):
            # [1 stycznia ~ 31 marca)
            return "winter", current_year
        if now < datetime(current_year, 7, 1):
            # [1 kwietnia ~ 30 czerwca)
            return "spring", current_year
        if now < datetime(current_year, 10, 1):
            # [1 lipca ~ 30 września)
            return "summer", current_year
        if now < datetime(current_year, 12, 1):
            # [1 października ~ 30 listopada)
            return "fall", current_year
        # [1 grudnia ~ 31 grudnia]
        return "winter", current_year

    @staticmethod
    def get_available_episodes(slug: str):
        """
        Get anime details from Docchi
        :param slug: anime slug
        :return: JSON response
        """

        url = f'{BASE_URL}/episodes/count/{slug}'

        resp = requests.get(url=url, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def search_anime(name: str):
        """
        Get anime details from Docchi
        :param name: anime name
        :return: JSON response
        """

        if name is None:
            raise Exception("A valid search string Must Be Provided")

        url = f'{BASE_URL}/series/related/{quote(name)}'

        resp = requests.get(url=url, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def get_anime_by_genre(genre: str):
        """
        Get anime details from Docchi
        :param genre: anime genre
        :return: JSON response
        """

        if genre is None:
            raise Exception("A valid genre Must Be Provided")

        url = f'{BASE_URL}/series/category?name={genre}&sort=DESC'

        resp = requests.get(url=url, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def get_anime_list(**kwargs):
        """
        Get anime list from Docchi
        :param kwargs: Additional query parameters
        :return: JSON response
        """

        url = f'{BASE_URL}/series/list'
        query_params = DocchiAPI.__to_query_string(kwargs)
        if query_params:
            url += f'?{query_params}'

        resp = requests.get(url=url, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def get_latest_episodes(season: str = None, year: str = None, **kwargs):
        """
        Get anime list from Docchi
        :param season: Season
        :param year: Year
        :param kwargs: Additional query parameters
        :return: JSON response
        """
        if not season and not year:
            url = f'{BASE_URL}/episodes/latest'
        else:
            url = f'{BASE_URL}/episodes/latest?season={season}&season_year={year}'
        query_params = DocchiAPI.__to_query_string(kwargs)
        if query_params:
            url += f'?{query_params}'

        try:
            resp = requests.get(url=url, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except HTTPError:
            logging.error(resp.text)


    @staticmethod
    def get_trending_anime(**kwargs):
        """
        Get trending anime list from Docchi
        :param kwargs: Additional query parameters
        :return: JSON response
        """

        url = f'{BASE_URL}/homepage/trending'
        query_params = DocchiAPI.__to_query_string(kwargs)
        if query_params:
            url += f'?{query_params}'

        resp = requests.get(url=url, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def get_seasonal_anime(season: str, year: str, **kwargs):
        """
        Get seasonal anime list from Docchi
        :param season: Season
        :param year: Year
        :param kwargs: Additional query parameters
        :return: JSON response
        """

        url = f'{BASE_URL}/homepage/season?season={season}&season_year={year}'
        query_params = DocchiAPI.__to_query_string(kwargs)
        if query_params:
            url += f'?{query_params}'

        resp = requests.get(url=url, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def __to_query_string(kwargs):
        """
        Convert Keyword arguments to a query string
        :param kwargs: The keyword arguments
        :return: query string
        """
        data = dict(**kwargs)
        return urlencode(data) if data else None
