# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import sys

from taskcluster import optionsFromEnvironment
from taskcluster.aio import Hooks
from tcadmin.util.sessions import aiohttp_session, with_aiohttp_session

from ciadmin.generate.ciconfig.projects import Project

TASK_URL = "{root_url}/tasks/{task_id}"
JSON_PUSH_URL = "{}/json-pushes?version=2&changeset={}"


@with_aiohttp_session
async def replay_hg_push(*, alias, revision):
    try:
        project = await Project.get(alias)
    except KeyError:
        sys.stderr.write("Unknown project alias: {}\n".format(alias))
        sys.exit(1)

    if not project.feature("hg-push"):
        sys.stderr.write("Project {} does not have hg-push feature.\n".format(alias))
        sys.exit(1)

    target_options = optionsFromEnvironment()
    target_hooks_api = Hooks(target_options, session=aiohttp_session())

    try:
        async with aiohttp_session().get(
            JSON_PUSH_URL.format(project.repo, revision)
        ) as response:
            response.raise_for_status()
            result = await response.json()
        pushes = result["pushes"]
    except Exception as e:
        sys.stderr.write(
            f"Could not get push info {alias} {revision} from hg.mozilla.org: {e}"
        )
        sys.exit(1)

    if len(pushes) != 1:
        print(
            "Changeset {} has {} associated pushes; "
            "only one expected".format(revision, len(pushes))
        )
        sys.exit(1)
    [(push_id, push_info)] = pushes.items()
    if revision not in push_info["changesets"]:
        print(
            "Changeset {} is not the tip {} of the associated push.".format(
                revision, push_info["changesets"][0]
            )
        )
        sys.exit(1)

    pulse_message = {
        "payload": {
            "type": "changegroup.1",
            "data": {
                "repo_url": project.repo,
                "heads": [revision],
                "pushlog_pushes": [
                    {
                        "user": (
                            push_info["user"]
                            if "@" in push_info["user"]
                            else push_info["user"] + "@noreply.mozilla.org"
                        ),
                        "pushid": int(push_id),
                        "time": push_info["date"],
                    }
                ],
            },
        },
        "_meta": {},
    }

    try:
        response = await target_hooks_api.triggerHook("hg-push", alias, pulse_message)
    except Exception as e:
        sys.stderr.write("Could not get create hg-push task: {}\n".format(e))
        sys.exit(1)

    print(
        TASK_URL.format(
            root_url=target_options["rootUrl"], task_id=response["status"]["taskId"]
        )
    )
