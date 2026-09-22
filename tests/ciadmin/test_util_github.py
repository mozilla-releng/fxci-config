# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from taskcluster.exceptions import TaskclusterFailure

from ciadmin.util import github

QUERY = 'query($owner:String!) { repository(owner:$owner, name:"x") { id } }'


def make_mock_client(response):
    client = AsyncMock()
    client.request = AsyncMock(return_value=response)
    return client


def make_response(body, status=200):
    response = MagicMock()
    response.ok = 200 <= status < 300
    response.status = status
    response.reason = "OK" if response.ok else "Forbidden"
    response.json = AsyncMock(return_value=body)
    response.text = AsyncMock(return_value=json.dumps(body))
    response.raise_for_status.side_effect = (
        None
        if response.ok
        else aiohttp.ClientResponseError(MagicMock(), MagicMock(), status=status)
    )
    return response


def patch_client(response):
    return patch(
        "ciadmin.util.github.get_client",
        AsyncMock(return_value=make_mock_client(response)),
    )


@pytest.mark.asyncio
async def test_graphql_returns_data_and_no_errors():
    response = make_response({"data": {"repository": {"id": "abc"}}})

    with patch_client(response) as get_client:
        data, errors = await github.graphql("mozilla/example", QUERY, owner="mozilla")

    assert data == {"repository": {"id": "abc"}}
    assert errors == []

    # The client is chosen per repository, so the repo path has to reach it.
    get_client.assert_awaited_once_with("mozilla/example")

    # The query and its variables go out as a POST body, not a URL.
    client = get_client.return_value
    client.request.assert_awaited_once_with(
        "POST", "/graphql", json={"query": QUERY, "variables": {"owner": "mozilla"}}
    )


NOT_FOUND = {
    "type": "NOT_FOUND",
    "path": ["repository", "refs", "nodes", 3, "target", "file"],
    "message": "Could not resolve file for path '.taskcluster.yml'.",
}
UNRUNNABLE = {"message": "Field 'nope' doesn't exist"}


@pytest.mark.parametrize(
    "data",
    (
        pytest.param(
            {"repository": {"refs": {"nodes": [{"name": "main"}]}}},
            id="partly-resolved",
        ),
        pytest.param(None, id="not-run-at-all"),
    ),
)
@pytest.mark.asyncio
async def test_graphql_errors(data):
    """Errors come back to the caller either way, rather than being raised.

    GitHub answers a partly resolvable query with both halves -- asking for a
    file that only some branches have returns those branches plus a NOT_FOUND
    for each that doesn't. A query it could not run at all returns a null
    `data`. Only the caller can tell those apart, so neither raises here.
    """
    errors = [NOT_FOUND if data else UNRUNNABLE]
    response = make_response({"data": data, "errors": errors})

    with patch_client(response):
        got_data, got_errors = await github.graphql(
            "mozilla/example", QUERY, owner="mozilla"
        )

    assert got_data == data
    assert got_errors == errors


@pytest.mark.asyncio
async def test_graphql_reports_an_http_error_before_raising(capsys):
    """The body is the only thing that says *why*, so it has to reach the log.

    Rate limiting and SAML enforcement are the two that come up in practice;
    neither is handled distinctly, so one case covers both.
    """
    body = {
        "message": "API rate limit exceeded for 1.2.3.4.",
        "documentation_url": "https://docs.github.com/rest/overview/resources-in-the-rest-api#rate-limiting",
    }
    response = make_response(body, status=403)

    with patch_client(response):
        with pytest.raises(aiohttp.ClientResponseError):
            await github.graphql("mozilla/example", QUERY, owner="mozilla")

    captured = capsys.readouterr()
    assert "403" in captured.err
    assert "API rate limit exceeded" in captured.err
    # stdout carries the diff itself, so diagnostics stay off it.
    assert captured.out == ""


@pytest.fixture(autouse=True)
def reset_clients():
    """Drop the module's client caches, which otherwise leak between tests."""
    yield
    github._clients.clear()
    github._client_locks.clear()
    github._warned.clear()
    github._fallback_client = None


@pytest.fixture
def projects(mock_ciconfig_file):
    """Stand in for projects.yml, which is where a token's repo list comes from."""

    def mocker(**projects):
        mock_ciconfig_file("projects.yml", projects)

    return mocker


def git_project(repo, **kwargs):
    return {
        "repo": repo,
        "repo_type": "git",
        "trust_domain": "foo",
        "branches": [{"name": "main", "level": 1}],
        "features": {"taskgraph-actions": True},
        **kwargs,
    }


@pytest.fixture
def taskcluster_credentials(monkeypatch):
    monkeypatch.setenv("TASKCLUSTER_CLIENT_ID", "static/test")
    monkeypatch.setenv("TASKCLUSTER_ACCESS_TOKEN", "quiet")


def token_response(token="s3cret", lifetime=timedelta(hours=1)):
    expires = datetime.now(UTC) + lifetime
    return {"token": token, "expires": expires.isoformat()}


def patch_auth(*responses, error=None):
    """Answer successive `auth.githubRepoToken` calls with `responses`."""
    auth = MagicMock()
    auth.return_value.githubRepoToken = AsyncMock(side_effect=error or list(responses))
    return patch("ciadmin.util.github.taskcluster.aio.Auth", auth)


@pytest.mark.asyncio
async def test_one_token_covers_the_owners_repositories(
    taskcluster_credentials, projects
):
    """The app, the owner and the permission all end up in the scope required.

    The repository list comes from projects.yml, so one call answers for every
    repository an owner has rather than one call each.
    """
    projects(
        private=git_project("https://github.com/mozilla-releng/staging-xpi-private"),
        config=git_project("https://github.com/mozilla-releng/fxci-config"),
        elsewhere=git_project("https://github.com/mozilla/example"),
        globbed=git_project("https://github.com/mozilla-releng/*"),
    )

    with patch_auth(token_response()) as auth:
        client = await github.get_client("mozilla-releng/staging-xpi-private")

    assert await client.auth.get_token() == "s3cret"
    auth.return_value.githubRepoToken.assert_awaited_once_with(
        "read",
        "mozilla-releng",
        {
            "repositories": ["fxci-config", "staging-xpi-private"],
            "permissions": {"contents": "read"},
        },
    )


@pytest.mark.asyncio
async def test_a_live_token_is_reused(taskcluster_credentials):
    with patch_auth(token_response("first"), token_response("second")) as auth:
        auth_source = github.OwnerTokenAuth("mozilla", ["example"])

        assert await auth_source.get_token() == "first"
        assert await auth_source.get_token() == "first"

    assert auth.return_value.githubRepoToken.await_count == 1


@pytest.mark.asyncio
async def test_a_token_near_expiry_is_replaced(taskcluster_credentials):
    """Github fixes the lifetime at an hour and will not extend it."""
    nearly_gone = token_response("first", github.REFRESH_MARGIN / 2)

    with patch_auth(nearly_gone, token_response("second")):
        auth_source = github.OwnerTokenAuth("mozilla", ["example"])

        assert await auth_source.get_token() == "first"
        assert await auth_source.get_token() == "second"


@pytest.mark.asyncio
async def test_one_client_per_owner(taskcluster_credentials, projects):
    """Two repositories of one owner share a client, and so share a token."""
    projects(
        one=git_project("https://github.com/mozilla/one"),
        two=git_project("https://github.com/mozilla/two"),
        other=git_project("https://github.com/taskcluster/three"),
    )

    with patch_auth(token_response("mozilla"), token_response("taskcluster")) as auth:
        one = await github.get_client("mozilla/one")
        two = await github.get_client("mozilla/two")
        other = await github.get_client("taskcluster/three")

    assert one is two
    assert one is not other
    assert auth.return_value.githubRepoToken.await_count == 2


@pytest.mark.asyncio
async def test_every_owner_that_falls_back_shares_one_client(
    taskcluster_credentials, projects, capsys
):
    """A pull request from a fork reaches no owner's token, and still runs."""
    projects(
        one=git_project("https://github.com/mozilla/one"),
        two=git_project("https://github.com/taskcluster/two"),
    )
    refusal = TaskclusterFailure("no scopes here")

    with patch_auth(error=refusal):
        with patch("ciadmin.util.github.client_from_env") as client_from_env:
            one = await github.get_client("mozilla/one")
            two = await github.get_client("taskcluster/two")

    assert one is two
    client_from_env.assert_called_once_with("mozilla-releng", ["fxci-config"])

    # One line per owner, not one per repository.
    assert capsys.readouterr().err.count("falling back") == 2


@pytest.mark.asyncio
async def test_a_refused_token_falls_back_and_says_so(taskcluster_credentials, capsys):
    """The message carries the scope the auth service asked for."""
    refusal = TaskclusterFailure(
        "Client ID static/test does not have sufficient scopes and is missing "
        "the following scopes:\n\nauth:github-repo-token:read/mozilla-releng/"
        "staging-xpi-private:contents:read"
    )

    with patch_auth(error=refusal):
        with patch("ciadmin.util.github.client_from_env") as client_from_env:
            client = await github.get_client("mozilla-releng/staging-xpi-private")

    assert client is client_from_env.return_value.return_value

    err = capsys.readouterr().err
    assert "auth:github-repo-token:read/mozilla-releng" in err
    assert "falling back" in err


@pytest.mark.asyncio
async def test_close_clients_closes_each_one_once(taskcluster_credentials, projects):
    projects(
        one=git_project("https://github.com/mozilla/one"),
        other=git_project("https://github.com/taskcluster/two"),
    )

    with patch_auth(token_response("one"), token_response("two")):
        one = await github.get_client("mozilla/one")
        two = await github.get_client("taskcluster/two")

    one.close = AsyncMock()
    two.close = AsyncMock()

    await github.close_clients()

    one.close.assert_awaited_once()
    two.close.assert_awaited_once()
    assert github._clients == {}
