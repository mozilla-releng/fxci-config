# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

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
        data, errors = await github.graphql(QUERY, owner="mozilla")

    assert data == {"repository": {"id": "abc"}}
    assert errors == []

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
        got_data, got_errors = await github.graphql(QUERY, owner="mozilla")

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
            await github.graphql(QUERY, owner="mozilla")

    captured = capsys.readouterr()
    assert "403" in captured.err
    assert "API rate limit exceeded" in captured.err
    # stdout carries the diff itself, so diagnostics stay off it.
    assert captured.out == ""
