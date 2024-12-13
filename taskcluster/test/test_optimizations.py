# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest
from pytest_taskgraph import make_task

from fxci_config_taskgraph import optimizations
from fxci_config_taskgraph.util.constants import FIREFOXCI_ROOT_URL, STAGING_ROOT_URL


@pytest.mark.parametrize(
    "task,files_changed_should_remove,expected",
    (
        pytest.param(
            {"provisionerId": "gecko-3", "workerType": "t-linux"},
            True,
            True,
            id="removed",
        ),
        pytest.param(
            {"provisionerId": "gecko-3", "workerType": "t-linux"},
            False,
            False,
            id="kept via files changed",
        ),
        pytest.param(
            {"provisionerId": "mozillavpn-3", "workerType": "b-linux-gcp-gw"},
            True,
            False,
            id="kept via worker type",
        ),
    ),
)
def test_integration_test_strategy(
    monkeypatch, mocker, task, files_changed_should_remove, expected
):
    monkeypatch.setenv("TASKCLUSTER_ROOT_URL", STAGING_ROOT_URL)

    diff_output = """
Registering resource: worker_pools
! WorkerPool=code-analysis-3/linux-gw-gcp (changed: config)
! WorkerPool=gecko-3/b-linux-2204-kvm-gcp (changed: config)
! WorkerPool=mozillavpn-3/b-linux-gcp-gw (changed: config)
"""

    mock_proc = mocker.MagicMock()
    mock_proc.stdout = diff_output

    mock_run = mocker.patch.object(
        optimizations.subprocess, "run", return_value=mock_proc
    )

    mock_files_changed = mocker.patch.object(
        optimizations.SkipUnlessChanged,
        "should_remove_task",
        return_value=files_changed_should_remove,
    )

    task = make_task(label="foo", task_def=task)
    opt = optimizations.IntegrationTestStrategy()
    assert opt.should_remove_task(task, "foo", "bar") == expected

    if mock_files_changed.called:
        mock_files_changed.assert_called_once_with(task, "foo", "bar")

    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    cmd = " ".join(args[0])
    assert "--environment firefoxci" in cmd
    assert "--resources worker_pools" in cmd
    assert kwargs["env"].get("TASKCLUSTER_ROOT_URL") == FIREFOXCI_ROOT_URL
