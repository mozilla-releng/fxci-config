# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import os
from asyncio import Lock

import aiohttp
from aiohttp_retry import ExponentialRetry, RetryClient
from tcadmin.util.sessions import aiohttp_session

from ciadmin import USER_AGENT

_cache = {}
_lock = {}


async def get(repo_path, repo_type="hg", revision=None, default_branch=None):
    """
    Get `.taskcluster.yml` from 'default' (or the given revision) at the named
    repo_path.  Note that this does not parse the yml (so that it can be hashed
    in its original form).

    If the file is not found, this returns None.
    """
    if repo_type == "hg":
        if revision is None:
            revision = default_branch or "default"
        url = f"{repo_path}/raw-file/{revision}/.taskcluster.yml"
    elif repo_type == "git":
        if revision is None:
            revision = default_branch or "master"
        if repo_path.startswith("https://github.com/"):
            if repo_path.endswith("/"):
                repo_path = repo_path[:-1]
            repo = repo_path.replace("https://github.com/", "")
            url = f"https://api.github.com/repos/{repo}/contents/.taskcluster.yml"
        elif repo_path.startswith("git@github.com:"):
            if repo_path.endswith(".git"):
                repo_path = repo_path[:-4]
            repo = repo_path.replace("git@github.com:", "")
            url = f"https://api.github.com/repos/{repo}/contents/.taskcluster.yml"
        else:
            raise Exception(
                f"Don't know how to determine file URL for non-github repo: {repo_path}"
            )
    else:
        raise Exception(f"Unknown repo_type {repo_type}!")

    cache_key = (url, revision)
    async with _lock.setdefault(cache_key, Lock()):
        if cache_key in _cache:
            return _cache[cache_key]

        client = RetryClient(
            client_session=aiohttp_session(),
            # Despite only setting 404 here, 5xx statuses will still be retried
            # for. See https://github.com/inyutin/aiohttp_retry?tab=readme-ov-file
            # for details.
            retry_options=ExponentialRetry(attempts=5, statuses={404}),
        )
        headers = {"User-Agent": USER_AGENT}
        params = {}
        # TODO: when we no longer need to support hg.mozilla.org here, we can
        # switch this to simple-github rather than doing this by hand.
        if "GITHUB_TOKEN" in os.environ and repo_type == "git":
            headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
            headers["Accept"] = "application/vnd.github.raw+json"
            params["ref"] = revision
        async with client.get(url, headers=headers, params=params) as response:
            try:
                response.raise_for_status()
                result = await response.read()
            except aiohttp.ClientResponseError as e:
                print(f"Got error when querying {url}: {e}")
                raise e

        _cache[cache_key] = result
        return _cache[cache_key]
