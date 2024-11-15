# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import subprocess

import taskcluster

ROOT_URL = "https://stage.taskcluster.nonprod.cloudops.mozgcp.net"
CLIENT_ID = "project/releng/fxci-config/apply"

assert "TASKCLUSTER_PROXY_URL" in os.environ
options = {"rootUrl": os.environ["TASKCLUSTER_PROXY_URL"]}
auth = taskcluster.Auth(options)

result = auth.resetAccessToken(CLIENT_ID)
assert result

token = result["accessToken"]
assert isinstance(token, str)

env = os.environ.copy()
del env["TASKCLUSTER_PROXY_URL"]  # ensure we don't use the proxy client
env.update(
    {
        "TASKCLUSTER_ROOT_URL": ROOT_URL,
        "TASKCLUSTER_CLIENT_ID": CLIENT_ID,
        "TASKCLUSTER_ACCESS_TOKEN": token,
    }
)
subprocess.run(["tc-admin", "apply", "--environment=staging"], env=env, check=True)
