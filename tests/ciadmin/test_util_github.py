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


def environment_config(**kwargs):
    return {
        "root_url": "https://tc.example.com",
        "modify_resources": [],
        "worker_manager": {},
        **kwargs,
    }


@pytest.fixture(autouse=True)
def environment(mock_ciconfig_file, set_environment):
    mock_ciconfig_file(
        "environments.yml",
        {
            "with_tokens": environment_config(),
            "without_tokens": environment_config(github_repo_tokens=False),
            "requiring_tokens": environment_config(require_github_tokens=True),
        },
    )
    with set_environment("with_tokens"):
        yield


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


@pytest.fixture
def no_taskcluster_credentials(monkeypatch):
    monkeypatch.delenv("TASKCLUSTER_CLIENT_ID", raising=False)
    monkeypatch.delenv("TASKCLUSTER_ACCESS_TOKEN", raising=False)


@pytest.fixture
def github_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")


@pytest.fixture
def no_github_credentials(monkeypatch):
    for name in ("GITHUB_TOKEN", "GITHUB_APP_ID", "GITHUB_APP_PRIVKEY"):
        monkeypatch.delenv(name, raising=False)


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
async def test_without_credentials_every_owner_shares_the_fallback(
    no_taskcluster_credentials, projects, capsys
):
    """A pull request from a fork has no credentials, and still runs."""
    projects(
        one=git_project("https://github.com/mozilla/one"),
        two=git_project("https://github.com/taskcluster/two"),
    )

    with patch_auth(token_response()) as auth:
        with patch("ciadmin.util.github.client_from_env") as client_from_env:
            one = await github.get_client("mozilla/one")
            two = await github.get_client("taskcluster/two")

    assert one is two
    client_from_env.assert_called_once_with("mozilla-releng", ["fxci-config"])

    # The auth service is never asked, and the run says why once, not per owner.
    auth.return_value.githubRepoToken.assert_not_awaited()
    assert capsys.readouterr().err.count("No Taskcluster credentials") == 1


REFUSAL = TaskclusterFailure(
    "Client ID static/test does not have sufficient scopes and is missing "
    "the following scopes:\n\nauth:github-repo-token:read/mozilla-releng/"
    "staging-xpi-private:contents:read"
)


@pytest.mark.asyncio
async def test_a_refused_token_fails_the_run_once_tokens_are_required(
    taskcluster_credentials, set_environment, capsys
):
    """With the switch on there is no fallback: a refusal is something to fix."""
    with set_environment("requiring_tokens"):
        with patch_auth(error=REFUSAL):
            with patch("ciadmin.util.github.client_from_env") as client_from_env:
                with pytest.raises(TaskclusterFailure):
                    await github.get_client("mozilla-releng/staging-xpi-private")

    client_from_env.assert_not_called()

    err = capsys.readouterr().err
    assert "github token for mozilla-releng" in err
    assert "auth:github-repo-token:read/mozilla-releng" in err


@pytest.mark.asyncio
async def test_an_owner_outside_the_enterprise_uses_the_environment_token(
    taskcluster_credentials, github_token, projects
):
    """The auth service has no app there, so it is never asked."""
    projects(
        jsone=git_project("https://github.com/json-e/json-e", github_enterprise=False),
        config=git_project("https://github.com/mozilla-releng/fxci-config"),
    )

    with patch_auth(token_response()) as auth:
        with patch("ciadmin.util.github.client_from_env") as client_from_env:
            outside = await github.get_client("json-e/json-e")
            inside = await github.get_client("mozilla-releng/fxci-config")

    assert outside is client_from_env.return_value.return_value
    assert inside is not outside
    auth.return_value.githubRepoToken.assert_awaited_once()
    assert not await github.has_repo_token("json-e/json-e")


@pytest.mark.asyncio
async def test_an_owner_outside_the_enterprise_needs_a_github_token(
    taskcluster_credentials, no_github_credentials, projects
):
    """Anonymous requests would hit the rate limit, so the run stops instead."""
    projects(
        jsone=git_project("https://github.com/json-e/json-e", github_enterprise=False)
    )

    with patch_auth(token_response()) as auth:
        with pytest.raises(Exception, match="GITHUB_TOKEN is required to read json-e"):
            await github.get_client("json-e/json-e")

    auth.return_value.githubRepoToken.assert_not_awaited()


@pytest.mark.asyncio
async def test_without_credentials_an_owner_outside_the_enterprise_is_not_checked(
    no_taskcluster_credentials, no_github_credentials, projects
):
    """Only a trusted run is expected to carry a GITHUB_TOKEN."""
    projects(
        jsone=git_project("https://github.com/json-e/json-e", github_enterprise=False)
    )

    with patch("ciadmin.util.github.client_from_env") as client_from_env:
        client = await github.get_client("json-e/json-e")

    assert client is client_from_env.return_value.return_value


@pytest.mark.asyncio
async def test_an_owners_repositories_must_agree_on_the_enterprise(
    taskcluster_credentials, github_token, projects
):
    """One app installation per owner cannot serve half of its repositories."""
    projects(
        one=git_project("https://github.com/mozilla/one"),
        two=git_project("https://github.com/mozilla/two", github_enterprise=False),
    )

    with pytest.raises(Exception, match="must have the same github_enterprise value"):
        await github.get_client("mozilla/one")


@pytest.mark.asyncio
async def test_has_repo_token_tells_a_token_from_the_fallback(monkeypatch, projects):
    projects(one=git_project("https://github.com/mozilla/one"))

    monkeypatch.setenv("TASKCLUSTER_CLIENT_ID", "static/test")
    monkeypatch.setenv("TASKCLUSTER_ACCESS_TOKEN", "quiet")
    with patch_auth(token_response()):
        assert await github.has_repo_token("mozilla/one")

    github._clients.clear()
    monkeypatch.delenv("TASKCLUSTER_CLIENT_ID")
    monkeypatch.delenv("TASKCLUSTER_ACCESS_TOKEN")
    with patch("ciadmin.util.github.client_from_env"):
        assert not await github.has_repo_token("mozilla/one")


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


@pytest.mark.asyncio
async def test_an_environment_without_repo_tokens_uses_the_fallback(
    taskcluster_credentials, projects, set_environment
):
    projects(
        one=git_project("https://github.com/mozilla/one"),
        two=git_project("https://github.com/taskcluster/two"),
    )

    with set_environment("without_tokens"):
        with patch_auth(token_response()) as auth:
            with patch("ciadmin.util.github.client_from_env") as client_from_env:
                one = await github.get_client("mozilla/one")
                two = await github.get_client("taskcluster/two")
                assert not await github.has_repo_token("mozilla/one")

    assert one is two
    assert one is client_from_env.return_value.return_value
    auth.return_value.githubRepoToken.assert_not_called()
