"""SQLite backend for anime mapping and slug cache."""
from app.db import connection


def load_anime_mapping(data: list):
    connection.execute("DELETE FROM anime_mapping")
    rows = []
    for item in data:
        imdb = item.get('imdb_id')
        if isinstance(imdb, list):
            imdb = imdb[0] if imdb else None
        rows.append((
            item.get('mal_id'),
            item.get('kitsu_id'),
            imdb,
            item.get('tvdb_id'),
            item.get('themoviedb_id'),
            item.get('season', {}).get('tvdb') if isinstance(item.get('season'), dict) else None,
        ))
    connection.executemany(
        "INSERT INTO anime_mapping (mal_id, kitsu_id, imdb_id, tvdb_id, themoviedb_id, season_tvdb) VALUES (?,?,?,?,?,?)",
        rows
    )
    connection.commit()


def _row_to_dict(row) -> dict:
    if not row:
        return None
    d = dict(row)
    if d.get('season_tvdb'):
        d['season'] = {'tvdb': d.pop('season_tvdb')}
    else:
        d.pop('season_tvdb', None)
    return {k: v for k, v in d.items() if v is not None}


def get_anime_by_mal_id(mal_id: int):
    row = connection.execute("SELECT * FROM anime_mapping WHERE mal_id=? LIMIT 1", (mal_id,)).fetchone()
    return _row_to_dict(row)


def get_anime_by_kitsu_id(kitsu_id: int):
    row = connection.execute("SELECT * FROM anime_mapping WHERE kitsu_id=? LIMIT 1", (kitsu_id,)).fetchone()
    return _row_to_dict(row)


def get_anime_by_imdb_id(imdb_id: str) -> list:
    rows = connection.execute("SELECT * FROM anime_mapping WHERE imdb_id=?", (imdb_id,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_slug_from_mal_id(mal_id) -> tuple:
    row = connection.execute("SELECT slug FROM slug_mapping WHERE mal_id=?", (int(mal_id),)).fetchone()
    return (True, row['slug']) if row else (False, None)


def get_mal_id_from_slug(slug) -> tuple:
    row = connection.execute("SELECT mal_id FROM slug_mapping WHERE slug=?", (slug,)).fetchone()
    return (True, row['mal_id']) if row else (False, None)


def save_slug_from_mal_id(mal_id, slug):
    connection.execute(
        "INSERT OR IGNORE INTO slug_mapping (mal_id, slug) VALUES (?,?)",
        (int(mal_id), slug)
    )
    connection.commit()
