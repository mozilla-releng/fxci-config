# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import os

import requests
import taskcluster

from fxci_config_taskgraph.util.constants import FIREFOXCI_ROOT_URL, STAGING_ROOT_URL


def get_firefoxci_credentials() -> dict[str, str]:
    """Retrieve credentials for the Firefox-CI instance that can access the
    required private artifacts.
    """
    assert os.environ["TASKCLUSTER_ROOT_URL"] == STAGING_ROOT_URL

    if "TASKCLUSTER_PROXY_URL" in os.environ:
        options = {"rootUrl": os.environ["TASKCLUSTER_PROXY_URL"]}
    else:
        options = taskcluster.optionsFromEnvironment()

    secrets = taskcluster.Secrets(options)

    result = secrets.get("project/releng/fxci-config/firefoxci-artifact-client")
    assert isinstance(result, dict)

    credentials = result["secret"]
    assert isinstance(credentials, dict)

    return credentials


def fetch_private_artifacts(task_id: str, artifacts: list[str]) -> None:
    """Retrieve artifacts from the specified task id."""
    options = {
        "rootUrl": FIREFOXCI_ROOT_URL,
        "credentials": get_firefoxci_credentials(),
    }
    queue = taskcluster.Queue(options)

    artifact_dir = os.environ["MOZ_ARTIFACT_DIR"]
    os.chdir(artifact_dir)

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
    print("\n  " + "\n  ".join(os.listdir(artifact_dir)))


if __name__ == "__main__":
    task_id = os.environ["FETCH_FIREFOXCI_TASK_ID"]
    artifacts = json.loads(os.environ["FETCH_FIREFOXCI_ARTIFACTS"])
    fetch_private_artifacts(task_id, artifacts)
