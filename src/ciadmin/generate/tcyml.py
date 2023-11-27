# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from asyncio import Lock

import aiohttp
from tcadmin.util.sessions import aiohttp_session

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
        url = "{}/raw-file/{}/.taskcluster.yml".format(repo_path, revision)
    elif repo_type == "git":
        if revision is None:
            revision = default_branch or "master"
        if repo_path.startswith("https://github.com/"):
            if repo_path.endswith("/"):
                repo_path = repo_path[:-1]
            url = "{}/raw/{}/.taskcluster.yml".format(repo_path, revision)
        elif repo_path.startswith("git@github.com:"):
            if repo_path.endswith(".git"):
                repo_path = repo_path[:-4]
            url = "{}/raw/{}/.taskcluster.yml".format(
                repo_path.replace("git@github.com:", "https://github.com/"), revision
            )
        else:
            raise Exception(
                "Don't know how to determine file URL for non-github "
                "repo: {}".format(repo_path)
            )
    else:
        raise Exception("Unknown repo_type {}!".format(repo_type))
    async with _lock.setdefault(repo_path, Lock()):
        if repo_path in _cache:
            return _cache[repo_path]

        try:
            async with aiohttp_session().get(url) as response:
                response.raise_for_status()
                result = await response.read()
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                result = None
            else:
                raise e

        _cache[repo_path] = result
        return _cache[repo_path]
