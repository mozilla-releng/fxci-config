# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

EVENT_ID = "26370a80-ed65-11e6-8f4c-80082678482d"
DEPLOY_ARGS = [
    "--deploy-repo",
    "mozilla-releng/fxci-config",
    "--deploy-workflow",
    "deploy.yml",
    "--deploy-ref",
    "main",
]

here = Path(__file__).parent
spec = importlib.util.spec_from_file_location(
    "redeploy_on_tcyml_change",
    here.parent / "scripts" / "redeploy-on-tcyml-change.py",
)
redeploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(redeploy)


def test_invalidates_hooks():
    with patch.object(redeploy.subprocess, "run") as run:
        run.return_value = MagicMock(stdout="true\n")
        assert redeploy.invalidates_hooks("mozilla-firefox/firefox", "main")

        # `false` must not come back truthy, as any non-empty string would.
        run.return_value = MagicMock(stdout="false\n")
        assert not redeploy.invalidates_hooks("mozilla-firefox/firefox", "main")

    command = run.call_args[0][0]
    assert command == [
        "uv",
        "run",
        "fxci",
        "invalidates-hooks",
        "mozilla-firefox/firefox",
        "main",
    ]
    # A failing fxci should raise rather than return empty output.
    assert run.call_args[1]["check"] is True


def test_invalidates_hooks_unexpected_output():
    with patch.object(redeploy.subprocess, "run") as run:
        run.return_value = MagicMock(stdout="Registering resource: hooks\n")
        with pytest.raises(Exception, match="Unexpected answer"):
            redeploy.invalidates_hooks("mozilla-firefox/firefox", "main")


def test_dispatch_deploy():
    with patch.object(redeploy.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = MagicMock(status=204)
        redeploy.dispatch_deploy(
            "s3cret", "mozilla-releng/fxci-config", "deploy.yml", "main"
        )

    request = urlopen.call_args[0][0]
    assert request.method == "POST"
    assert request.full_url == (
        "https://api.github.com/repos/mozilla-releng/fxci-config"
        "/actions/workflows/deploy.yml/dispatches"
    )
    assert request.headers["Authorization"] == "Bearer s3cret"
    # Nothing but the branch may cross the repository boundary.
    assert json.loads(request.data) == {"ref": "main"}


def test_main_dispatches_nothing(monkeypatch, capsys):
    """The pushes that leave every hook intact"""
    with (
        patch.object(redeploy, "invalidates_hooks") as invalidates_hooks,
        patch.object(redeploy, "dispatch_deploy") as dispatch,
        patch.object(redeploy.taskcluster, "Secrets") as secrets,
    ):
        monkeypatch.setenv("ORGANIZATION", "mozilla-firefox")
        monkeypatch.setenv("REPOSITORY", "firefox")
        monkeypatch.setenv("REF", "refs/tags/v1.0")
        monkeypatch.setenv("EVENT_ID", EVENT_ID)
        redeploy.main(DEPLOY_ARGS)
        assert "is not a branch" in capsys.readouterr().out
        # A tag is discarded before projects.yml is consulted at all.
        invalidates_hooks.assert_not_called()

        invalidates_hooks.return_value = False
        monkeypatch.setenv("ORGANIZATION", "octocat")
        monkeypatch.setenv("REPOSITORY", "hello-world")
        monkeypatch.setenv("REF", "refs/heads/main")
        monkeypatch.setenv("EVENT_ID", EVENT_ID)
        redeploy.main(DEPLOY_ARGS)
        assert "No hook is generated from" in capsys.readouterr().out

    dispatch.assert_not_called()
    # Neither push may reach for the deploy credential.
    secrets.assert_not_called()


def test_main_managed_repo_dispatches(monkeypatch):
    monkeypatch.setenv("ORGANIZATION", "mozilla-firefox")
    monkeypatch.setenv("REPOSITORY", "firefox")
    monkeypatch.setenv("REF", "refs/heads/main")
    monkeypatch.setenv("EVENT_ID", EVENT_ID)
    monkeypatch.setenv("TASKCLUSTER_PROXY_URL", "http://taskcluster")
    monkeypatch.setenv("TASKCLUSTER_SECRET", "project/releng/fxci-config/deploy-token")

    with (
        patch.object(redeploy, "invalidates_hooks", return_value=True),
        patch.object(redeploy, "dispatch_deploy") as dispatch,
        patch.object(redeploy.taskcluster, "Secrets") as secrets,
    ):
        secrets.return_value.get.return_value = {"secret": {"token": "s3cret"}}
        redeploy.main(DEPLOY_ARGS)

    secrets.return_value.get.assert_called_once_with(
        "project/releng/fxci-config/deploy-token"
    )
    dispatch.assert_called_once_with(
        "s3cret", "mozilla-releng/fxci-config", "deploy.yml", "main"
    )


def test_main_lookup_failure_is_fatal(monkeypatch):
    # A broken lookup must fail the task rather than silently skip the deploy.
    with (
        patch.object(
            redeploy.subprocess,
            "run",
            side_effect=subprocess.CalledProcessError(1, "fxci"),
        ),
        patch.object(redeploy, "dispatch_deploy") as dispatch,
    ):
        monkeypatch.setenv("ORGANIZATION", "mozilla-firefox")
        monkeypatch.setenv("REPOSITORY", "firefox")
        monkeypatch.setenv("REF", "refs/heads/main")
        monkeypatch.setenv("EVENT_ID", EVENT_ID)
        with pytest.raises(subprocess.CalledProcessError):
            redeploy.main(DEPLOY_ARGS)

    dispatch.assert_not_called()
