from . import database
from tinydb import Query
from typing import Optional, List

anime = Query()
mapping_table = database.table('anime_mapping')

# Anime mapping functions
def load_anime_mapping(data: list):
    """Load anime mapping data to TinyDB"""
    mapping_table.truncate()
    mapping_table.insert_multiple(data)

def get_anime_by_mal_id(mal_id: int) -> Optional[dict]:
    """Get anime by MAL ID"""
    results = mapping_table.search(anime.mal_id == mal_id)
    return results[0] if results else None

def get_anime_by_kitsu_id(kitsu_id: int) -> Optional[dict]:
    """Get anime by Kitsu ID"""
    results = mapping_table.search(anime.kitsu_id == kitsu_id)
    return results[0] if results else None

def get_anime_by_imdb_id(imdb_id: str) -> List[dict]:
    """Get anime by IMDB ID (can return multiple for different seasons)"""
    results = mapping_table.search(
        (anime.imdb_id == imdb_id) | 
        (anime.imdb_id.test(lambda v: isinstance(v, list) and imdb_id in v))
    )
    return results

# Slug mapping functions


def get_slug_from_mal_id(mal_id) -> (bool, str):
    """
    Get slug from mal_id from TinyDB
    :param mal_id: The MyAnimeList id of the anime
    :return: A tuple of (found, slug)
    """
    if res := database.search(anime.mal_id == mal_id):
        return True, res[0]['slug']
    return False, None


def get_mal_id_from_slug(slug) -> (bool, str):
    """
    Get mal_id from slug from TinyDB
    :param slug: The Docchi slug of the anime
    :return: A tuple of (found, mal_id)
    """
    if res := database.search(anime.slug == slug):
        return True, res[0]['mal_id']
    return False, None


def save_slug_from_mal_id(mal_id, slug):
    """
    Save slug mapping to TinyDB
    :param mal_id: The MyAnimeList id of the anime
    :param slug: The Docchi slug of the anime
    """
    exists, saved_slug = get_slug_from_mal_id(int(mal_id))
    if not saved_slug:
        database.insert({'mal_id': mal_id, 'slug': slug})


def save_mal_id_from_slug(slug, mal_id):
    """
    Save slug mapping to TinyDB
    :param slug: The Docchi slug of the anime
    :param mal_id: The MyAnimeList id of the anime
    """
    exists, saved_mal_id = get_mal_id_from_slug(slug)
    if not saved_mal_id:
        database.insert({'mal_id': int(mal_id), 'slug': slug})
