# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from unittest.mock import AsyncMock, call

import aiohttp
import pytest
from aiohttp.client_reqrep import RequestInfo
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from ciadmin.util import github


def make_client_response_error(status):
    headers = CIMultiDictProxy(CIMultiDict())
    request_info = RequestInfo(
        URL("https://api.github.com/repos/mozilla/example"),
        "GET",
        headers,
    )
    return aiohttp.ClientResponseError(
        request_info=request_info,
        history=(),
        status=status,
        message="test",
        headers=headers,
    )


def make_response(mocker, status=None):
    response = mocker.Mock()
    if status is None:
        response.raise_for_status.return_value = None
    else:
        response.raise_for_status.side_effect = make_client_response_error(status)
    return response


@pytest.mark.asyncio
async def test_request_with_retry_retries_502_three_times(mocker):
    responses = [
        make_response(mocker, status=502),
        make_response(mocker, status=502),
        make_response(mocker),
    ]
    client = mocker.Mock()
    client.request = AsyncMock(side_effect=responses)

    mocker.patch("ciadmin.util.github.get_client", new=AsyncMock(return_value=client))
    sleep = AsyncMock()
    mocker.patch("ciadmin.util.github.asyncio.sleep", new=sleep)

    result = await github.request_with_retry("GET", "/repos/mozilla/example")

    assert result is responses[2]
    assert client.request.await_count == 3
    responses[0].release.assert_called_once_with()
    responses[1].release.assert_called_once_with()
    responses[2].release.assert_not_called()
    assert sleep.await_args_list == [call(1), call(2)]


@pytest.mark.asyncio
async def test_request_with_retry_raises_after_max_attempts_on_502(mocker):
    responses = [make_response(mocker, status=502) for _ in range(3)]
    client = mocker.Mock()
    client.request = AsyncMock(side_effect=responses)

    mocker.patch("ciadmin.util.github.get_client", new=AsyncMock(return_value=client))
    sleep = AsyncMock()
    mocker.patch("ciadmin.util.github.asyncio.sleep", new=sleep)

    with pytest.raises(aiohttp.ClientResponseError) as exc:
        await github.request_with_retry("GET", "/repos/mozilla/example")

    assert exc.value.status == 502
    assert client.request.await_count == 3
    responses[0].release.assert_called_once_with()
    responses[1].release.assert_called_once_with()
    responses[2].release.assert_not_called()
    assert sleep.await_args_list == [call(1), call(2)]


@pytest.mark.asyncio
async def test_request_with_retry_does_not_retry_non_retryable_status(mocker):
    response = make_response(mocker, status=404)
    client = mocker.Mock()
    client.request = AsyncMock(return_value=response)

    mocker.patch("ciadmin.util.github.get_client", new=AsyncMock(return_value=client))
    sleep = AsyncMock()
    mocker.patch("ciadmin.util.github.asyncio.sleep", new=sleep)

    with pytest.raises(aiohttp.ClientResponseError) as exc:
        await github.request_with_retry("GET", "/repos/mozilla/example")

    assert exc.value.status == 404
    assert client.request.await_count == 1
    response.release.assert_not_called()
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_with_retry_rejects_zero_attempts():
    with pytest.raises(ValueError, match="attempts must be at least 1"):
        await github.request_with_retry("GET", "/repos/mozilla/example", attempts=0)
