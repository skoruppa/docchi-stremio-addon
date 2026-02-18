import logging
import aiohttp
from urllib.parse import urlencode, quote
from datetime import datetime

BASE_URL = "https://api.docchi.pl/v1"
TIMEOUT = 30


class DocchiAPI:
    """
    Async Docchi API wrapper
    """

    def __init__(self):
        """
        Initialize the Docchi API wrapper
        """
        # Don't create session in __init__

    async def _make_request(self, url: str):
        """Make HTTP request with proper session management"""
        timeout = aiohttp.ClientTimeout(total=TIMEOUT)
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=10)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.json(content_type=None)

    async def close(self):
        """Close the session"""
        pass  # No session to close

    async def get_anime_details(self, slug: str):
        """
        Get anime details from Docchi
        :param slug: anime slug
        :return: JSON response
        """
        if slug is None:
            raise Exception("A Valid Anime slug Must Be Provided")

        url = f'{BASE_URL}/series/find/{slug}'
        return await self._make_request(url)

    async def get_episode_players(self, slug: str, episode: int):
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
            return await self._make_request(url)
        except aiohttp.ClientError:
            return None

    async def get_slug_from_mal_id(self, mal_id: str):
        """
        Get anime details from Docchi
        :param mal_id: anime slug
        :return: slug
        """
        if mal_id is None:
            raise Exception("A Valid mal id Must Be Provided")

        url = f'{BASE_URL}/series/related/{mal_id}'
        related_items = await self._make_request(url)
        for item in related_items:
            if item['mal_id'] == int(mal_id):
                return item['slug']
        return None

    @staticmethod
    def get_current_season():
        """
        Get current anime season (by actual airing period)
        :return: tuple of (season, season_year)
        """
        now = datetime.now()
        year = now.year
        month = now.month

        if month <= 3:
            return "winter", year
        elif month <= 6:
            return "spring", year
        elif month <= 9:
            return "summer", year
        else:
            return "fall", year

    async def get_available_episodes(self, slug: str):
        """
        Get anime details from Docchi
        :param slug: anime slug
        :return: JSON response
        """
        url = f'{BASE_URL}/episodes/count/{slug}'
        return await self._make_request(url)

    async def search_anime(self, name: str):
        """
        Get anime details from Docchi
        :param name: anime name
        :return: JSON response
        """
        if name is None:
            raise Exception("A valid search string Must Be Provided")

        url = f'{BASE_URL}/series/related/{quote(name)}'
        return await self._make_request(url)

    async def get_anime_by_genre(self, genre: str):
        """
        Get anime details from Docchi
        :param genre: anime genre
        :return: JSON response
        """
        if genre is None:
            raise Exception("A valid genre Must Be Provided")

        url = f'{BASE_URL}/series/category?name={genre}&sort=DESC'
        try:
            return await self._make_request(url)
        except aiohttp.ClientError as e:
            logging.error(f"Docchi API error (genre): {e}")
            return []

    async def get_anime_list(self, **kwargs):
        """
        Get anime list from Docchi
        :param kwargs: Additional query parameters
        :return: JSON response
        """
        url = f'{BASE_URL}/series/list'
        query_params = self.__to_query_string(kwargs)
        if query_params:
            url += f'?{query_params}'
        return await self._make_request(url)

    async def get_latest_episodes(self, season: str = None, year: str = None, **kwargs):
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
        query_params = self.__to_query_string(kwargs)
        if query_params:
            url += f'&{query_params}' if '?' in url else f'?{query_params}'

        try:
            return await self._make_request(url)
        except aiohttp.ClientError as e:
            logging.error(f"Docchi API error (latest): {e}")
            return []

    async def get_recent_episodes(self, season: str = None, year: str = None):
        """
        Get recent episodes from Docchi
        :param season: Season
        :param year: Year
        :return: JSON response
        """
        if not season and not year:
            season, year = self.get_current_season()
        url = f'{BASE_URL}/episodes/recent?season_year={year}&season={season}'
        try:
            return await self._make_request(url)
        except aiohttp.ClientError as e:
            logging.error(f"Docchi API error (recent): {e}")
            return []

    async def get_trending_anime(self, **kwargs):
        """
        Get trending anime list from Docchi
        :param kwargs: Additional query parameters
        :return: JSON response
        """
        url = f'{BASE_URL}/homepage/trending'
        query_params = self.__to_query_string(kwargs)
        if query_params:
            url += f'?{query_params}'

        try:
            return await self._make_request(url)
        except aiohttp.ClientError as e:
            logging.error(f"Docchi API error (trending): {e}")
            return []

    async def get_seasonal_anime(self, season: str, year: str, **kwargs):
        """
        Get seasonal anime list from Docchi
        :param season: Season
        :param year: Year
        :param kwargs: Additional query parameters
        :return: JSON response
        """
        url = f'{BASE_URL}/homepage/season?season={season}&season_year={year}'
        query_params = self.__to_query_string(kwargs)
        if query_params:
            url += f'&{query_params}'

        try:
            return await self._make_request(url)
        except aiohttp.ClientError as e:
            logging.error(f"Docchi API error (seasonal): {e}")
            return []

    @staticmethod
    def __to_query_string(kwargs):
        """
        Convert Keyword arguments to a query string
        :param kwargs: The keyword arguments
        :return: query string
        """
        data = dict(**kwargs)
        return urlencode(data) if data else None
