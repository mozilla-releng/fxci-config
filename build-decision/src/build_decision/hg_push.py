# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import json
import logging
import os
import time

from .decision import render_tc_yml

logger = logging.getLogger(__name__)


# Allow triggering on-push task for pushes up to 3 days old.
MAX_TIME_DRIFT = 3 * 24 * 60 * 60


def get_revision_from_pulse_message():
    pulse_message = json.loads(os.environ["PULSE_MESSAGE"])
    print("Pulse Message:")
    print(json.dumps(pulse_message, indent=4, sort_keys=True))

    pulse_payload = pulse_message["payload"]
    if pulse_payload["type"] != "changegroup.1":
        print("Not a changegroup.1 message")
        return

    push_count = len(pulse_payload["data"]["pushlog_pushes"])
    if push_count != 1:
        print("Message has {} pushes; only one supported".format(push_count))
        return

    head_count = len(pulse_payload["data"]["heads"])
    if head_count != 1:
        print("Message has {} heads; only one supported".format(head_count))
        return

    return pulse_payload["data"]["heads"][0]


def build_decision(*, repository, taskcluster_yml_repo, dry_run):
    # The hg-push hook can be triggered manually, so we throw out everything
    # from the input, other than the revision, and get the pushinfo from
    # hg.mozilla.org.
    revision = get_revision_from_pulse_message()

    push = repository.get_push_info(revision=revision)

    if time.time() - push["pushdate"] > MAX_TIME_DRIFT:
        logger.warn("Push is too old, not triggering tasks")
        return

    if taskcluster_yml_repo is None:
        taskcluster_yml = repository.get_file(".taskcluster.yml", revision=revision)
    else:
        taskcluster_yml = taskcluster_yml_repo.get_file(".taskcluster.yml")

    task = render_tc_yml(
        taskcluster_yml,
        tasks_for="hg-push",
        push=push,
        repository=repository.to_json(),
    )

    task.display()
    if not dry_run:
        task.submit()
