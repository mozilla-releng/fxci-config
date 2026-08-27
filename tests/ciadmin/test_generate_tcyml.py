# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import hashlib

import pytest

# graphql-core arrives with simple-github, by way of gql.
from graphql import parse
from tcadmin.util.sessions import with_aiohttp_session

from ciadmin.generate import tcyml
from ciadmin.util import github

# pin a revision of mozilla-central so we know what to expect
PINNED_REV = "ff8505d177b9"


@pytest.mark.asyncio
@with_aiohttp_session
async def test_get_tcyml():
    res = await tcyml.get("https://hg.mozilla.org/mozilla-central", revision=PINNED_REV)
    await github.close_client()
    assert hashlib.sha512(res).hexdigest()[:10] == "684648599a"


def git_oid(content):
    """The oid git would store `content` under."""
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


MAIN = b"tasks:\n  - task: main\n"
RELEASE = b"tasks:\n  - task: release\n"


@pytest.fixture(autouse=True)
def clear_blob_oid_cache():
    tcyml._blob_oid_cache.clear()
    tcyml._blob_oid_lock.clear()
    yield
    tcyml._blob_oid_cache.clear()
    tcyml._blob_oid_lock.clear()


def refs_page(branches, has_next_page=False, cursor=None):
    """Build a `_BLOB_OIDS_QUERY` response out of {branch: oid or None}."""
    return {
        "repository": {
            "refs": {
                "pageInfo": {"hasNextPage": has_next_page, "endCursor": cursor},
                "nodes": [
                    {
                        "name": name,
                        "target": (
                            {"file": {"object": {"oid": oid}}}
                            if oid
                            else {"file": None}
                        ),
                    }
                    for name, oid in branches.items()
                ],
            }
        }
    }


MISSING_FILE = {
    "type": "NOT_FOUND",
    "path": ["repository", "refs", "nodes", 1, "target", "file"],
    "message": "Could not resolve file for path '.taskcluster.yml'.",
}


def fake_graphql(*responses):
    """Answer successive `github.graphql` calls with `(data, errors)` pairs."""
    calls = []

    async def graphql(query, **variables):
        calls.append((query, variables))
        return responses[len(calls) - 1]

    graphql.calls = calls
    return graphql


@pytest.mark.asyncio
async def test_get_blob_oids(monkeypatch):
    """Each branch maps to the oid of its `.taskcluster.yml`."""
    graphql = fake_graphql(
        (refs_page({"main": git_oid(MAIN), "release": git_oid(RELEASE)}), [])
    )
    monkeypatch.setattr(tcyml.github, "graphql", graphql)

    oids = await tcyml.get_blob_oids("mozilla/example")

    assert oids == {"main": git_oid(MAIN), "release": git_oid(RELEASE)}
    assert len(graphql.calls) == 1
    assert graphql.calls[0][1] == {
        "owner": "mozilla",
        "name": "example",
        "after": None,
    }


@pytest.mark.asyncio
async def test_get_blob_oids_maps_a_branch_without_the_file_to_none(monkeypatch):
    """A branch that moved `.taskcluster.yml` away isn't an error."""
    graphql = fake_graphql(
        (
            refs_page({"main": git_oid(MAIN), "ancient": None}),
            [MISSING_FILE],
        )
    )
    monkeypatch.setattr(tcyml.github, "graphql", graphql)

    oids = await tcyml.get_blob_oids("mozilla/example")

    assert oids == {"main": git_oid(MAIN), "ancient": None}


@pytest.mark.asyncio
async def test_get_blob_oids_follows_pagination(monkeypatch):
    graphql = fake_graphql(
        (refs_page({"main": git_oid(MAIN)}, has_next_page=True, cursor="MTAw"), []),
        (refs_page({"release": git_oid(RELEASE)}), []),
    )
    monkeypatch.setattr(tcyml.github, "graphql", graphql)

    oids = await tcyml.get_blob_oids("mozilla/example")

    assert oids == {"main": git_oid(MAIN), "release": git_oid(RELEASE)}
    assert [call[1]["after"] for call in graphql.calls] == [None, "MTAw"]


@pytest.mark.parametrize(
    "data,errors,expected",
    (
        pytest.param(
            "page",
            [{"type": "RATE_LIMITED", "message": "slow down"}],
            "slow down",
            id="a-real-error",
        ),
        pytest.param(
            "page",
            [MISSING_FILE, {"type": "RATE_LIMITED", "message": "slow down"}],
            "slow down",
            id="a-real-error-among-benign-ones",
        ),
        pytest.param(
            None,
            [{"message": "Could not resolve to a Repository"}],
            "Could not resolve to a Repository",
            id="query-did-not-run",
        ),
    ),
)
@pytest.mark.asyncio
async def test_get_blob_oids_raises_unless_the_only_errors_are_missing_files(
    monkeypatch, data, errors, expected
):
    """A missing `.taskcluster.yml` is the one error we carry on through.

    `github.graphql` hands back a null `data` rather than raising on it, so
    that case has to stop here too.
    """
    page = refs_page({"main": git_oid(MAIN)}) if data == "page" else None
    graphql = fake_graphql((page, errors))
    monkeypatch.setattr(tcyml.github, "graphql", graphql)

    with pytest.raises(RuntimeError, match=expected):
        await tcyml.get_blob_oids("mozilla/example")


@pytest.mark.asyncio
async def test_get_blob_oids_caches_per_repo(monkeypatch):
    """Asked twice, a repo is fetched once -- and never confused with another."""
    graphql = fake_graphql(
        (refs_page({"main": git_oid(MAIN)}), []),
        (refs_page({"trunk": git_oid(RELEASE)}), []),
    )
    monkeypatch.setattr(tcyml.github, "graphql", graphql)

    one = await tcyml.get_blob_oids("mozilla/one")
    two = await tcyml.get_blob_oids("mozilla/two")

    assert one == {"main": git_oid(MAIN)}
    assert two == {"trunk": git_oid(RELEASE)}
    assert await tcyml.get_blob_oids("mozilla/one") == one
    assert [call[1]["name"] for call in graphql.calls] == ["one", "two"]


@pytest.mark.asyncio
async def test_get_blobs_fetches_every_oid_in_one_request(monkeypatch):
    oids = {git_oid(MAIN), git_oid(RELEASE)}
    ordered = sorted(oids)
    contents = {git_oid(MAIN): MAIN, git_oid(RELEASE): RELEASE}
    graphql = fake_graphql(
        (
            {
                "repository": {
                    f"blob{i}": {
                        "isTruncated": False,
                        "text": contents[oid].decode(),
                    }
                    for i, oid in enumerate(ordered)
                }
            },
            [],
        )
    )
    monkeypatch.setattr(tcyml.github, "graphql", graphql)

    blobs = await tcyml.get_blobs("mozilla/example", oids)

    assert blobs == contents
    assert len(graphql.calls) == 1
    # Both oids are asked for by the one query.
    query = graphql.calls[0][0]
    for oid in oids:
        assert f'object(oid: "{oid}")' in query


@pytest.mark.asyncio
async def test_get_blobs_asks_for_nothing_when_given_nothing(monkeypatch):
    graphql = fake_graphql()
    monkeypatch.setattr(tcyml.github, "graphql", graphql)

    assert await tcyml.get_blobs("mozilla/example", set()) == {}
    assert graphql.calls == []


@pytest.mark.asyncio
async def test_get_blobs_rejects_content_that_does_not_match_its_oid(monkeypatch):
    """Hook ids are derived from these bytes, so a mismatch has to be fatal."""
    graphql = fake_graphql(
        (
            {"repository": {"blob0": {"isTruncated": False, "text": "tampered\n"}}},
            [],
        )
    )
    monkeypatch.setattr(tcyml.github, "graphql", graphql)

    with pytest.raises(RuntimeError, match="changed in transit"):
        await tcyml.get_blobs("mozilla/example", {git_oid(MAIN)})


@pytest.mark.asyncio
async def test_get_blobs_rejects_truncated_content(monkeypatch):
    graphql = fake_graphql(
        (
            {"repository": {"blob0": {"isTruncated": True, "text": MAIN.decode()}}},
            [],
        )
    )
    monkeypatch.setattr(tcyml.github, "graphql", graphql)

    with pytest.raises(RuntimeError, match="truncated"):
        await tcyml.get_blobs("mozilla/example", {git_oid(MAIN)})


@pytest.mark.asyncio
async def test_get_blobs_rejects_content_that_is_not_text(monkeypatch):
    """GraphQL returns a null `text` for a blob it can't decode as UTF-8."""
    graphql = fake_graphql(
        ({"repository": {"blob0": {"isTruncated": False, "text": None}}}, [])
    )
    monkeypatch.setattr(tcyml.github, "graphql", graphql)

    with pytest.raises(RuntimeError, match="isn't UTF-8 text"):
        await tcyml.get_blobs("mozilla/example", {git_oid(MAIN)})


@pytest.mark.asyncio
async def test_get_blobs_raises_on_errors(monkeypatch):
    graphql = fake_graphql(
        ({"repository": {"blob0": None}}, [{"message": "Something went wrong"}])
    )
    monkeypatch.setattr(tcyml.github, "graphql", graphql)

    with pytest.raises(RuntimeError, match="Something went wrong"):
        await tcyml.get_blobs("mozilla/example", {git_oid(MAIN)})


@pytest.mark.asyncio
async def test_the_generated_blobs_query_is_valid_graphql(monkeypatch):
    """`get_blobs` assembles its query by hand, out of a variable oid count.

    Every other test mocks the transport, so a syntax error in what it builds
    would otherwise only surface against the live API.
    """
    sent = []

    async def capture(query, **variables):
        sent.append(query)
        return {"repository": {}}, [{"message": "stop here"}]

    monkeypatch.setattr(tcyml.github, "graphql", capture)

    oids = {git_oid(MAIN), git_oid(RELEASE)}
    with pytest.raises(RuntimeError, match="stop here"):
        await tcyml.get_blobs("mozilla/example", oids)

    (query,) = sent
    parse(query)
