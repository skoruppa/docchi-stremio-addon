import logging
import requests
from urllib.parse import urlencode, quote
from requests import HTTPError

BASE_URL = "https://kitsu.app/api/edge"
TIMEOUT = 30


class KitsuAPI:
    """
    Kitsu API wrapper
    """

    def __init__(self):
        """
        Initialize the Docchi API wrapper
        """

    @staticmethod
    def get_mal_id_from_kitsu_id(kitsu_id: str):
        """
        Get mal id from kitsu id
        :param kitsu_id: kitsu id
        :return: JSON response
        """

        if kitsu_id is None:
            raise Exception("A Valid kitsu id ug Must Be Provided")

        url = f'{BASE_URL}/anime/{kitsu_id}/mappings'
        try:
            resp = requests.get(url=url, timeout=TIMEOUT)
            resp.raise_for_status()
        except requests.exceptions.HTTPError:
            return None
        mappings = resp.json()
        for mapping in mappings['data']:
            if mapping['attributes']['externalSite'] == 'myanimelist/anime':
                return mapping['attributes']['externalId']
        return None

    @staticmethod
    def get_kitsu_from_mal_id(mal_id: str):
        """
        Get mal id from kitsu id
        :param mal_id: mal id
        :return: JSON response
        """

        if mal_id is None:
            raise Exception("A mal id Must Be Provided")

        url = f'{BASE_URL}/mappings?filter[externalSite]=myanimelist%2Fanime&filter[externalId]={mal_id}&include=item'

        resp = requests.get(url=url, timeout=TIMEOUT)
        resp.raise_for_status()
        try:
            return resp.json()['data'][0]['relationships']['item']['data']['id']
        except KeyError:
            return None
