# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import hashlib
import sys
from asyncio import Lock

import aiohttp
from aiohttp_retry import ExponentialRetry, RetryClient
from tcadmin.util.sessions import aiohttp_session

from ciadmin import USER_AGENT
from ciadmin.util import github

_cache = {}
_lock = {}

_blob_oid_cache = {}
_blob_oid_lock = {}

# 100 is the most GraphQL will return in one page.
_BLOB_OIDS_QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    refs(refPrefix: "refs/heads/", first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        target {
          ... on Commit {
            file(path: ".taskcluster.yml") {
              object { ... on Blob { oid } }
            }
          }
        }
      }
    }
  }
}
"""


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
            async with client.get(url, headers=headers, params=params) as response:
                try:
                    response.raise_for_status()
                    result = await response.read()
                except aiohttp.ClientResponseError as e:
                    print(f"Got error when querying {url}: {e}", file=sys.stderr)
                    raise e

            _cache[cache_key] = result

    elif repo_type == "git":
        if revision is None:
            revision = default_branch or "master"
        if repo_path.startswith("https://github.com/"):
            if repo_path.endswith("/"):
                repo_path = repo_path[:-1]
            repo = repo_path.replace("https://github.com/", "")
            endpoint = f"/repos/{repo}/contents/.taskcluster.yml"
        elif repo_path.startswith("git@github.com:"):
            if repo_path.endswith(".git"):
                repo_path = repo_path[:-4]
            repo = repo_path.replace("git@github.com:", "")
            endpoint = f"/repos/{repo}/contents/.taskcluster.yml"
        else:
            raise Exception(
                f"Don't know how to determine file URL for non-github repo: {repo_path}"
            )

        cache_key = (endpoint, revision)

        async with _lock.setdefault(cache_key, Lock()):
            if cache_key in _cache:
                return _cache[cache_key]

            headers = {"Accept": "application/vnd.github.raw+json"}
            params = {"ref": revision}

            client = await github.get_client()
            response = await client.request(
                "GET", endpoint, headers=headers, params=params
            )
            try:
                response.raise_for_status()
                result = await response.read()
            except aiohttp.ClientResponseError as e:
                print(f"Got error when querying {endpoint}: {e}", file=sys.stderr)
                raise e

            _cache[cache_key] = result

    else:
        raise Exception(f"Unknown repo_type {repo_type}!")

    return _cache[cache_key]


def _only_missing_files(errors):
    """Whether `errors` are all "this branch has no `.taskcluster.yml`".

    A branch without the file is normal -- a project owner can move it away to
    disable Taskcluster -- and GitHub reports it as a NOT_FOUND against the
    `file` field while still resolving every other branch.
    """
    return all(
        error.get("type") == "NOT_FOUND" and error.get("path", [])[-1:] == ["file"]
        for error in errors
    )


# TODO: support private repositories. this will most likely require querying
# GitHub as an app.
async def get_blob_oids(repo_path):
    """
    Map each branch of the github repository at `repo_path` to the git blob oid
    of its `.taskcluster.yml`, or to None where the branch doesn't have one.
    Only supported for public GitHub repositories.

    The oid is git's own hash of the file, so branches sharing a
    `.taskcluster.yml` share an oid, and the file itself only has to be
    downloaded once per distinct version. See `get_blobs`.
    """
    owner, name = repo_path.split("/")

    async with _blob_oid_lock.setdefault(repo_path, Lock()):
        if repo_path in _blob_oid_cache:
            return _blob_oid_cache[repo_path]

        oids = {}
        after = None
        while True:
            data, errors = await github.graphql(
                _BLOB_OIDS_QUERY, owner=owner, name=name, after=after
            )
            if not _only_missing_files(errors):
                raise RuntimeError(
                    f"Got errors listing the branches of {repo_path}: {errors}"
                )

            refs = data["repository"]["refs"]
            for node in refs["nodes"]:
                blob = (node.get("target") or {}).get("file") or {}
                oids[node["name"]] = (blob.get("object") or {}).get("oid")

            if not refs["pageInfo"]["hasNextPage"]:
                break
            after = refs["pageInfo"]["endCursor"]

        _blob_oid_cache[repo_path] = oids
        return oids


async def get_blobs(repo_path, blob_oids):
    """
    Download the given git blobs from the github repository at `repo_path`,
    returning {blob oid: content}.

    Every blob comes back in one request, so a repository whose hundred
    branches share a dozen distinct `.taskcluster.yml`s costs a single call.
    """
    if not blob_oids:
        return {}

    owner, name = repo_path.split("/")
    # A GraphQL alias can't start with a digit, so oids can't be used as-is.
    aliases = {f"blob{i}": oid for i, oid in enumerate(sorted(blob_oids))}
    fields = "\n    ".join(
        f'{alias}: object(oid: "{oid}") {{ ... on Blob {{ isTruncated text }} }}'
        for alias, oid in aliases.items()
    )
    query = (
        "query($owner: String!, $name: String!) {\n"
        "  repository(owner: $owner, name: $name) {\n"
        f"    {fields}\n"
        "  }\n"
        "}\n"
    )

    data, errors = await github.graphql(query, owner=owner, name=name)
    if errors:
        raise RuntimeError(f"Got errors fetching blobs from {repo_path}: {errors}")

    repository = data["repository"]
    return {
        oid: _blob_content(repository[alias], oid, repo_path)
        for alias, oid in aliases.items()
    }


def _blob_content(blob, oid, repo_path):
    """
    Return a blob's bytes, checked against the oid github indexed it under.

    GraphQL returns file contents as a decoded string, and the hash that names
    an action hook has to be taken over the exact bytes git stores, since it
    must match the hashing in taskgraph's `actions/registry.py`. Re-deriving
    the oid is what makes that safe to rely on: a hash that is wrong renames
    every action hook, and neither a test nor a review would catch it.

    The decoding itself looks trustworthy -- every `.taskcluster.yml` in
    projects.yml round-trips exactly, as do files with far heavier multibyte
    content. The one failure mode measured is size: github truncates `text`
    at 512KB, and says so in `isTruncated`.
    """
    if blob is None or blob.get("text") is None:
        raise RuntimeError(
            f"{repo_path}: blob {oid} has no text; a `.taskcluster.yml` that "
            "isn't UTF-8 text cannot be used"
        )
    if blob["isTruncated"]:
        raise RuntimeError(
            f"{repo_path}: blob {oid} was truncated by github and cannot be hashed"
        )

    content = blob["text"].encode("utf-8")
    # How git names a blob: sha1 over "blob <bytes>\0" and the content.
    actual = hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()
    if actual != oid:
        raise RuntimeError(
            f"{repo_path}: blob {oid} hashes as {actual}; refusing to generate "
            "hook ids from content that changed in transit"
        )

    return content
