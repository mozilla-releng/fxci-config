# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import os

import requests
import taskcluster

from fxci_config_taskgraph.util.constants import FIREFOXCI_ROOT_URL, STAGING_ROOT_URL

if "TASKCLUSTER_PROXY_URL" in os.environ:
    options = {"rootUrl": os.environ["TASKCLUSTER_PROXY_URL"]}
else:
    options = taskcluster.optionsFromEnvironment()
    assert options["rootUrl"] == STAGING_ROOT_URL

secrets = taskcluster.Secrets(options)

result = secrets.get("project/releng/fxci-config/firefoxci-artifact-client")
assert isinstance(result, dict)

credentials = result["secret"]
assert isinstance(credentials, dict)

options = {"rootUrl": FIREFOXCI_ROOT_URL, "credentials": credentials}
queue = taskcluster.Queue(options)

artifact_dir = os.environ["MOZ_ARTIFACT_DIR"]
os.chdir(artifact_dir)

task_id = os.environ["FETCH_FIREFOXCI_TASK_ID"]
artifacts = json.loads(os.environ["FETCH_FIREFOXCI_ARTIFACTS"])
for artifact in artifacts:
    print(f"Downloading task {task_id} artifact: {artifact}")
    result = queue.getLatestArtifact(task_id, artifact)
    assert result

    url = result["url"]
    assert isinstance(url, str)

    with requests.get(url, stream=True) as resp:
        resp.raise_for_status()

        name = artifact.rsplit("/", 1)[-1]
        dest = f"{artifact_dir}/{name}"
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024):
                fh.write(chunk)

print(f"Files in {artifact_dir}:")
print("\n".join(os.listdir(artifact_dir)))
