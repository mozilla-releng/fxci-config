# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from ciadmin.generate import branches as branches_module


def make_mock_client(response):
    client = AsyncMock()
    client.request = AsyncMock(return_value=response)
    return client


def make_403_response(body_text):
    response = MagicMock()
    response.ok = False
    response.status = 403
    response.reason = "Forbidden"
    response.text = AsyncMock(return_value=body_text)
    response.raise_for_status.side_effect = aiohttp.ClientResponseError(
        MagicMock(), MagicMock(), status=403
    )
    return response


@pytest.mark.asyncio
async def test_get_403_rate_limit_exceeded(capsys):
    branches_module._cache.clear()
    body = json.dumps(
        {
            "message": "API rate limit exceeded for 1.2.3.4. (But here's the good news: Authenticated requests get a higher rate limit. Check out the documentation for more details.)",
            "documentation_url": "https://docs.github.com/rest/overview/resources-in-the-rest-api#rate-limiting",
        }
    )
    response = make_403_response(body)
    client = make_mock_client(response)

    with patch(
        "ciadmin.generate.branches.github.get_client", AsyncMock(return_value=client)
    ):
        with pytest.raises(aiohttp.ClientResponseError):
            await branches_module.get("mozilla-releng/fxci-config")

    captured = capsys.readouterr()
    assert "403" in captured.out
    assert "API rate limit exceeded" in captured.out


@pytest.mark.asyncio
async def test_get_403_saml_enforcement(capsys):
    branches_module._cache.clear()
    body = json.dumps(
        {
            "message": "Resource protected by organization SAML enforcement. You must grant your Personal Access token access to this organization.",
            "documentation_url": "https://docs.github.com/articles/authenticating-to-a-github-organization-with-saml-single-sign-on/",
            "status": "403",
        }
    )
    response = make_403_response(body)
    client = make_mock_client(response)

    with patch(
        "ciadmin.generate.branches.github.get_client", AsyncMock(return_value=client)
    ):
        with pytest.raises(aiohttp.ClientResponseError):
            await branches_module.get("taskcluster/taskgraph")

    captured = capsys.readouterr()
    assert "403" in captured.out
    assert "SAML enforcement" in captured.out
