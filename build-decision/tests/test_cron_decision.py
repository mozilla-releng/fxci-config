# coding=utf-8

import pytest

import build_decision.cron.decision as decision


@pytest.mark.parametrize(
    "job, expected",
    (
        ({}, []),
        (
            {
                "target-tasks-method": "target",
            },
            ["--target-tasks-method=target"],
        ),
        (
            {
                "target-tasks-method": "target",
                "include-push-tasks": True,
            },
            ["--target-tasks-method=target", "--include-push-tasks"],
        ),
        (
            {
                "optimize-target-tasks": ["one", "two"],
                "rebuild-kinds": ["three", "four"],
            },
            [
                "--optimize-target-tasks=['one', 'two']",
                "--rebuild-kind=three",
                "--rebuild-kind=four",
            ],
        ),
    ),
)
def test_make_arguments(job, expected):
    """Add coverage for cron.decision.make_arguments."""
    assert decision.make_arguments(job) == expected


@pytest.mark.parametrize("dry_run", (True, False))
def test_run_decision_task(mocker, dry_run):
    """Add coverage for cron.decision.run_decision_task."""
    fake_hook = mocker.MagicMock()
    fake_repo = mocker.MagicMock()
    fake_repo.get_file.return_value = {"tc": True}

    def fake_render(*args, **kwargs):
        return fake_hook

    mocker.patch.object(decision, "render_tc_yml", new=fake_render)
    mocker.patch.object(decision, "make_arguments", return_value=["--option=arg"])

    decision.run_decision_task(
        "job_name",
        {"treeherder-symbol": "x"},
        repository=fake_repo,
        push_info={"revision": "rev"},
        dry_run=dry_run,
    )

    if not dry_run:
        fake_hook.submit.assert_called_once_with()
    else:
        fake_hook.submit.assert_not_called()
