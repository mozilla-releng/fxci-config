import json
import os

import pytest

import build_decision.git_push as git_push

HOOK_PAYLOAD = {
    "base_sha": "def456abc123def456abc123def456abc123def4",
    "head_sha": "abc123def456abc123def456abc123def456abc1",
    "base_ref": None,
    "ref": "refs/heads/main",
    "owner": "dev@example.com",
}


@pytest.mark.parametrize(
    "dry_run",
    (
        True,
        False,
    ),
)
def test_build_decision(mocker, dry_run):
    """Add coverage for git_push.build_decision."""
    taskcluster_root_url = "http://taskcluster.local"

    fake_repo = mocker.MagicMock()
    fake_repo.repo_url = "https://github.com/mozilla-releng/fxci-config"
    fake_repo.repo_path = "mozilla-releng/fxci-config"
    fake_task = mocker.MagicMock()

    mocker.patch.object(
        os,
        "environ",
        new={
            "TASKCLUSTER_ROOT_URL": taskcluster_root_url,
            "HOOK_PAYLOAD": json.dumps(HOOK_PAYLOAD),
        },
    )
    mock_render = mocker.patch.object(git_push, "render_tc_yml", return_value=fake_task)

    git_push.build_decision(
        repository=fake_repo,
        dry_run=dry_run,
    )

    fake_repo.get_file.assert_called_once_with(
        ".taskcluster.yml",
        revision=HOOK_PAYLOAD["head_sha"],
    )

    mock_render.assert_called_once()
    render_kwargs = mock_render.call_args[1]
    assert render_kwargs["taskcluster_root_url"] == taskcluster_root_url
    assert render_kwargs["tasks_for"] == "git-push"
    assert callable(render_kwargs["as_slugid"])
    assert render_kwargs["event"] == {
        "ref": "refs/heads/main",
        "before": HOOK_PAYLOAD["base_sha"],
        "after": HOOK_PAYLOAD["head_sha"],
        "base_ref": None,
        "pusher": {"email": "dev@example.com"},
        "repository": {
            "name": "fxci-config",
            "full_name": "mozilla-releng/fxci-config",
            "html_url": "https://github.com/mozilla-releng/fxci-config",
            "clone_url": "https://github.com/mozilla-releng/fxci-config.git",
        },
    }

    if dry_run:
        fake_task.submit.assert_not_called()
    else:
        fake_task.submit.assert_called_once_with()


def test_as_slugid_memoized(mocker):
    """as_slugid returns the same value for the same label."""
    mocker.patch.object(
        os,
        "environ",
        new={
            "TASKCLUSTER_ROOT_URL": "http://taskcluster.local",
            "HOOK_PAYLOAD": json.dumps(HOOK_PAYLOAD),
        },
    )
    fake_repo = mocker.MagicMock()
    fake_repo.repo_url = "https://github.com/org/repo"
    fake_repo.repo_path = "org/repo"

    captured = {}

    def capture_render(tc_yml, **context):
        captured["as_slugid"] = context["as_slugid"]
        result = mocker.MagicMock()
        return result

    mocker.patch.object(git_push, "render_tc_yml", side_effect=capture_render)

    git_push.build_decision(
        repository=fake_repo,
        dry_run=True,
    )

    as_slugid = captured["as_slugid"]
    assert as_slugid("label1") == as_slugid("label1")
    assert as_slugid("label1") != as_slugid("label2")
