from . import database
from tinydb import Query


anime = Query()


def get_slug_from_mal_id(mal_id) -> (bool, str):
    """
    Get kitsu_id from mal_id from db
    :param mal_id: The MyAnimeList id of the anime
    :return: A tuple of (found, slug)
    """
    if res := database.search(anime.mal_id == mal_id):
        return True, res[0]['slug']
    return False, None


def get_mal_id_from_slug(slug) -> (bool, str):
    """
    Get kitsu_id from mal_id from db
    :param slug: The MyAnimeList id of the anime
    :return: A tuple of (found, mal_id)
    """
    if res := database.search(anime.slug == slug):
        return True, res[0]['mal_id']
    return False, None


def save_slug_from_mal_id(mal_id, slug):
    """
    Get kitsu_id from mal_id from db
    :param mal_id: The MyAnimeList id of the anime
    :param slug: The Docchi slug of the anime
    """
    exists, saved_slug = get_slug_from_mal_id(int(mal_id))
    if not saved_slug:
        database.insert({'mal_id': mal_id, 'slug': slug})


def save_mal_id_from_slug(slug, mal_id):
    """
    Get kitsu_id from mal_id from db
    :param slug: The Docchi slug of the anime
    :param mal_id: The MyAnimeList id of the anime
    """
    exists, saved_mal_id = get_mal_id_from_slug(slug)
    if not saved_mal_id:
        database.insert({'mal_id': int(mal_id), 'slug': slug})
