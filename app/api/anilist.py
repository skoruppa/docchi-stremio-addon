"""AniList GraphQL API client for resolving anime relations."""
import logging
import aiohttp

ANILIST_URL = "https://graphql.anilist.co"
TIMEOUT = aiohttp.ClientTimeout(total=15)

_QUERY_BY_MAL = '''
query ($idMal: Int) {
  Media(idMal: $idMal, type: ANIME) {
    id
    idMal
    format
    relations {
      edges {
        relationType
        node { id idMal format type }
      }
    }
  }
}
'''

_QUERY_BY_ID = '''
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    idMal
    format
    relations {
      edges {
        relationType
        node { id idMal format type }
      }
    }
  }
}
'''


async def get_tv_prequel_chain(mal_id: int, max_steps: int = 10) -> list[dict]:
    """Walk back through PREQUEL relations (TV format only) starting from a MAL ID.

    Returns a list of prequel entries in order (closest first), each with:
        - anilist_id: AniList ID
        - mal_id: MAL ID (may be None)
        - steps: how many PREQUEL hops from the original

    Stops when no more TV PREQUEL is found or max_steps is reached.
    """
    results = []
    visited = set()

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # First request by MAL ID
            async with session.post(
                ANILIST_URL,
                json={'query': _QUERY_BY_MAL, 'variables': {'idMal': int(mal_id)}}
            ) as resp:
                if resp.status != 200:
                    return results
                data = await resp.json()

            media = data.get('data', {}).get('Media')
            if not media:
                return results

            visited.add(media['id'])
            steps = 0

            while steps < max_steps:
                # Find PREQUEL relation (TV format, ANIME type only)
                prequel = None
                for edge in media.get('relations', {}).get('edges', []):
                    if (edge.get('relationType') == 'PREQUEL' and
                            edge['node'].get('type') == 'ANIME' and
                            edge['node'].get('format') == 'TV' and
                            edge['node']['id'] not in visited):
                        prequel = edge['node']
                        break

                if not prequel:
                    break

                steps += 1
                visited.add(prequel['id'])
                results.append({
                    'anilist_id': prequel['id'],
                    'mal_id': prequel.get('idMal'),
                    'steps': steps,
                })

                # Fetch next prequel's relations
                async with session.post(
                    ANILIST_URL,
                    json={'query': _QUERY_BY_ID, 'variables': {'id': prequel['id']}}
                ) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()

                media = data.get('data', {}).get('Media')
                if not media:
                    break

    except Exception as e:
        logging.warning(f"[AniList] get_tv_prequel_chain failed for mal:{mal_id}: {e}")

    return results


async def get_tv_sequel_mal_id(mal_id: int, steps: int = 1) -> int | None:
    """Walk forward through SEQUEL relations (TV format only) and return the MAL ID
    that is `steps` sequels ahead.

    Args:
        mal_id: Starting MAL ID
        steps: How many SEQUEL hops to take (1 = direct sequel)

    Returns:
        MAL ID of the sequel at the given step, or None if not found.
    """
    visited = set()

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            # First request by MAL ID
            async with session.post(
                ANILIST_URL,
                json={'query': _QUERY_BY_MAL, 'variables': {'idMal': int(mal_id)}}
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            media = data.get('data', {}).get('Media')
            if not media:
                return None

            visited.add(media['id'])
            current_step = 0

            while current_step < steps:
                # Find SEQUEL relation (TV format, ANIME type only)
                sequel = None
                for edge in media.get('relations', {}).get('edges', []):
                    if (edge.get('relationType') == 'SEQUEL' and
                            edge['node'].get('type') == 'ANIME' and
                            edge['node'].get('format') == 'TV' and
                            edge['node']['id'] not in visited):
                        sequel = edge['node']
                        break

                if not sequel:
                    return None

                current_step += 1
                visited.add(sequel['id'])

                if current_step == steps:
                    return sequel.get('idMal')

                # Fetch next sequel's relations
                async with session.post(
                    ANILIST_URL,
                    json={'query': _QUERY_BY_ID, 'variables': {'id': sequel['id']}}
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()

                media = data.get('data', {}).get('Media')
                if not media:
                    return None

    except Exception as e:
        logging.warning(f"[AniList] get_tv_sequel_mal_id failed for mal:{mal_id} steps={steps}: {e}")

    return None
