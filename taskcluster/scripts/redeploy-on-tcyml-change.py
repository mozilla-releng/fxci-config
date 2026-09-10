# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Redeploy fxci-config when a repository it generates hooks for changes its
`.taskcluster.yml`.

Run from a hook bound to taskcluster-github's `taskcluster-yml-update`
exchange. A push in one repository causes a deploy of another, so the message
is only ever used to look things up: the repository and ref are handed to
`fxci invalidates-hooks`, and the dispatch carries no inputs. The most this
can ever do is redeploy whatever is already on the deploy ref.
"""

import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request

import taskcluster

BRANCH_PREFIX = "refs/heads/"


def invalidates_hooks(repo_path, branch):
    """Whether a push to `repo_path` `branch` leaves one of our hooks stale."""
    answer = subprocess.run(
        ["uv", "run", "fxci", "invalidates-hooks", repo_path, branch],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    if answer not in ("true", "false"):
        raise Exception(f"Unexpected answer from fxci invalidates-hooks: {answer!r}")
    return answer == "true"


def dispatch_deploy(token, repo, workflow, ref):
    endpoint = (
        f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
    )
    request = urllib.request.Request(
        endpoint,
        data=json.dumps({"ref": ref}).encode(),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            print(f"Dispatched {workflow} on {ref}: {response.status}")
    except urllib.error.HTTPError as e:
        print(f"Got error when querying {endpoint}: {e.code} {e.reason}: {e.read()}")
        raise e


def parse_args(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--deploy-repo",
        required=True,
        help="Repository to dispatch the deploy workflow in, as `owner/repo`",
    )
    parser.add_argument(
        "--deploy-workflow",
        required=True,
        help="File name of the workflow to dispatch (e.g. `deploy.yml`)",
    )
    parser.add_argument(
        "--deploy-ref",
        required=True,
        help="Ref of --deploy-repo to dispatch the workflow on",
    )
    return parser.parse_args(args)


def main(args=None):
    args = parse_args(args)
    repo_path = f"{os.environ['ORGANIZATION']}/{os.environ['REPOSITORY']}"
    ref = os.environ["REF"]
    print(f"Handling delivery {os.environ['EVENT_ID']} for {repo_path} {ref}.")

    # Only branches are hashed, so a tag can never make a hook stale.
    if not ref.startswith(BRANCH_PREFIX):
        print(f"{ref} is not a branch, nothing to do.")
        return
    branch = ref[len(BRANCH_PREFIX) :]

    if not invalidates_hooks(repo_path, branch):
        print(f"No hook is generated from {repo_path} {branch}, nothing to do.")
        return

    print(f"{repo_path} changed its .taskcluster.yml on {branch}, redeploying.")
    assert "TASKCLUSTER_PROXY_URL" in os.environ
    secrets = taskcluster.Secrets({"rootUrl": os.environ["TASKCLUSTER_PROXY_URL"]})
    secret = secrets.get(os.environ["TASKCLUSTER_SECRET"])
    dispatch_deploy(
        secret["secret"]["token"],
        args.deploy_repo,
        args.deploy_workflow,
        args.deploy_ref,
    )


if __name__ == "__main__":
    main()
