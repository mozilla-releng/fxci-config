# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import functools

from .repository import Repository
from .secrets import get_secret
from .util.cli import CLI

app = CLI("Build decision tasks")


def repo_arguments(app):
    def decorator(func):
        @app.argument("--repo-url", required=True)
        @app.argument("--project", required=True)
        @app.argument("--level", required=True)
        @app.argument("--repository-type", required=True)
        @app.argument("--trust-domain", required=True)
        @app.argument("--github-token-secret")
        @functools.wraps(func)
        def wrapper(args):
            repository = {}
            for argument in (
                "repo_url",
                "project",
                "level",
                "repository_type",
                "trust_domain",
            ):
                repository[argument] = args.pop(argument)
            github_token_secret = args.pop("github_token_secret", None)
            if github_token_secret:
                repository["github_token"] = get_secret(
                    github_token_secret, secret_key="token"
                )
            args["repository"] = Repository(**repository)
            func(args)

        return wrapper

    return decorator


@app.command("hg-push", help="Create an hg-push decision task.")
@repo_arguments(app)
@app.argument("--taskcluster-yml-repo")
@app.argument("--dry-run", action="store_true")
def hg_push(options):
    from .hg_push import build_decision

    if options["taskcluster_yml_repo"]:
        taskcluster_yml_repo = Repository(
            repo_url=options["taskcluster_yml_repo"],
            repository_type="hg",
        )
    else:
        taskcluster_yml_repo = None
    build_decision(
        repository=options["repository"],
        taskcluster_yml_repo=taskcluster_yml_repo,
        dry_run=options["dry_run"],
    )


@app.command("cron", help="Process `.cron.yml`.")
@repo_arguments(app)
@app.argument("--branch")
@app.argument("--force-run")
@app.argument("--dry-run", action="store_true")
def cron(options):
    from .cron import run

    run(
        repository=options["repository"],
        branch=options["branch"],
        force_run=options["force_run"],
        dry_run=options["dry_run"],
    )


main = app.main
