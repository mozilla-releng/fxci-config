# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from asyncio import Lock

from ciadmin.util import github

_default_branch_cache = {}
_default_branch_lock = {}


async def get_default_branch(repo_path):
    """Get the default branch of a GitHub repository."""
    if repo_path.endswith("/"):
        repo_path = repo_path[:-1]
    endpoint = f"/repos/{repo_path}"

    async with _default_branch_lock.setdefault(repo_path, Lock()):
        if repo_path in _default_branch_cache:
            return _default_branch_cache[repo_path]

        client = await github.get_client()
        response = await client.request("GET", endpoint)
        if not response.ok:
            detail = await response.text()
            print(
                f"Got error when querying {endpoint}: "
                f"{response.status} {response.reason}: {detail}"
            )
            response.raise_for_status()

        _default_branch_cache[repo_path] = (await response.json())["default_branch"]
        return _default_branch_cache[repo_path]
