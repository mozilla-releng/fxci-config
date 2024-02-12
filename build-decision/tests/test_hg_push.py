# coding=utf-8

import json
import os
import time

import pytest

import build_decision.hg_push as hg_push


@pytest.mark.parametrize(
    "pulse_payload, expected",
    (
        (
            # None if `pulse_payload["type"] != "changegroup.1"
            {"type": "unknown"},
            None,
        ),
        (
            # None if len(pushlog_pushes) == 0
            {"type": "changegroup.1", "data": {"pushlog_pushes": []}},
            None,
        ),
        (
            # None if len(pushlog_pushes) > 1
            {"type": "changegroup.1", "data": {"pushlog_pushes": ["one", "two"]}},
            None,
        ),
        (
            # None if len(heads) == 0
            {"type": "changegroup.1", "data": {"pushlog_pushes": ["one"], "heads": []}},
            None,
        ),
        (
            # None if len(heads) > 1
            {
                "type": "changegroup.1",
                "data": {"pushlog_pushes": ["one"], "heads": ["rev1", "rev2"]},
            },
            None,
        ),
        (
            # Success!
            {
                "type": "changegroup.1",
                "data": {"pushlog_pushes": ["one"], "heads": ["rev1"]},
            },
            "rev1",
        ),
    ),
)
def test_get_revision_from_pulse_message(mocker, pulse_payload, expected):
    """Add coverage for hg_push.get_revision_from_pulse_message."""
    pulse_message = json.dumps({"payload": pulse_payload})
    mocker.patch.object(os, "environ", new={"PULSE_MESSAGE": pulse_message})
    assert hg_push.get_revision_from_pulse_message() == expected


@pytest.mark.parametrize(
    "push_age, use_tc_yml_repo, dry_run",
    (
        (
            # Ignore; too old
            hg_push.MAX_TIME_DRIFT + 5000,
            False,
            False,
        ),
        (
            # Don't ignore, dry run
            500,
            False,
            True,
        ),
        (
            # Don't ignore, use_tc_yml_repo
            1000,
            True,
            False,
        ),
    ),
)
def test_build_decision(mocker, push_age, use_tc_yml_repo, dry_run):
    """Add coverage for hg_push.build_decision."""
    now_timestamp = 1649974668
    push = {"pushdate": now_timestamp - push_age}
    fake_repo = mocker.MagicMock()
    fake_repo.get_push_info.return_value = push
    fake_tc_yml_repo = mocker.MagicMock()
    fake_task = mocker.MagicMock()

    mocker.patch.object(hg_push, "get_revision_from_pulse_message", return_value="rev")
    mocker.patch.object(time, "time", return_value=now_timestamp)
    mocker.patch.object(hg_push, "render_tc_yml", return_value=fake_task)

    args = {
        "repository": fake_repo,
        "taskcluster_yml_repo": fake_tc_yml_repo if use_tc_yml_repo else None,
        "dry_run": dry_run,
    }

    hg_push.build_decision(**args)
    if not dry_run and push_age <= hg_push.MAX_TIME_DRIFT:
        fake_task.submit.assert_called_once_with()
    else:
        fake_task.submit.assert_not_called()
