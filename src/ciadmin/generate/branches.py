# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from asyncio import Lock

import aiohttp
from simple_github import client_from_env

_cache = {}
_lock = {}


# TODO: support private repositories. this will most likely require querying
# GitHub as an app.
async def get(repo_path, repo_type="git"):
    """Get the list of branches present in `repo_path`. Only supported for
    public GitHub repositories."""
    if repo_type != "git":
        raise Exception("Branches can only be fetched for git repositories!")

    if repo_path.endswith("/"):
        repo_path = repo_path[:-1]
    branches_endpoint = f"/repos/{repo_path}/branches"

    # 100 is the maximum allowed
    # https://docs.github.com/en/rest/branches/branches?apiVersion=2022-11-28#list-branches
    params = {"per_page": 100}
    headers = {}
    client_cls = client_from_env("mozilla-releng", ["fxci-config"])

    async with _lock.setdefault(repo_path, Lock()):
        if repo_path in _cache:
            return _cache[repo_path]

        async with client_cls() as client:
            branches = []
            while branches_endpoint:
                response = await client.request(
                    "GET", branches_endpoint, headers=headers, params=params
                )
                try:
                    response.raise_for_status()
                    result = await response.json()
                    branches.extend([b["name"] for b in result])
                    # If `link` is present in the response it will contain
                    # pagination information. We need to examine it to see
                    # if there are additional pages of results to fetch.
                    # See https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api?apiVersion=2022-11-28#using-link-headers
                    # for a full description of the responses.
                    # This icky parsing can probably go away when we switch
                    # to a GitHub app, as we'll likely be using a proper
                    # client at that point.
                    for l in response.headers.get("link", "").split(","):
                        if 'rel="next"' in l:
                            branches_endpoint = l.split(">")[0].split("<")[1]
                            branches_endpoint = branches_endpoint[
                                len("https://api.github.com") :
                            ]
                            break
                    else:
                        branches_endpoint = None
                except aiohttp.ClientResponseError as e:
                    print(f"Got error when querying {branches_endpoint}: {e}")
                    raise e

            _cache[repo_path] = branches
            return _cache[repo_path]
