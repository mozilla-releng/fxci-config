# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import functools
import json
import sys

import yaml
from tcadmin.appconfig import AppConfig
from tcadmin.main import run_async

from .utils.cli import CLI

app = CLI("Interact with firefox-ci cluster")


def ciconfig_arguments(app, *, use_environment=True):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(args):
            from ciadmin.boot import appconfig

            ac = AppConfig()

            if use_environment and "environment" in args:
                ac.options = {"--environment": args.pop("environment")}

            with AppConfig._as_current(ac):
                func(args)

        if use_environment:
            wrapper = app.argument(
                "--environment",
                required=True,
                help="environment for which resources are to be generated",
            )(wrapper)

        return wrapper

    return decorator


def show_json(value, sort_keys=True):
    print(json.dumps(value, sort_keys=sort_keys, indent=2, separators=(",", ": ")))


def show_yaml(value, sort_keys=True):
    yaml.safe_dump(
        value, stream=sys.stdout, default_flow_style=False, sort_keys=sort_keys
    )


FORMATS = {"json": show_json, "yaml": show_yaml}


def format_arguments(app):
    def decorator(func):
        @app.argument(
            "--json",
            "-J",
            action="store_const",
            dest="format",
            const="json",
            help="Output workers as a JSON object",
        )
        @app.argument(
            "--yaml",
            "-Y",
            action="store_const",
            dest="format",
            const="yaml",
            help="Output task graph as a YAML object (default)",
        )
        @functools.wraps(func)
        def wrapper(args):
            args["formatter"] = FORMATS[args.pop("format") or "yaml"]
            return func(args)

        return wrapper

    return decorator


@app.command(
    "check-worker-secrets",
    help="Verify that all workers in ci-configuration "
    "have the necessary secrets defined.",
    description="This does not require any scopes, "
    "but does not verify that the secrets are up-to-date.",
)
@ciconfig_arguments(app)
@run_async
async def check_worker_secrets(options):
    from .worker_secrets import check_worker_secrets

    await check_worker_secrets()


@app.command(
    "create-worker-secrets",
    help="Create secrets for all workers that need them.",
    description="This requires scopes to get and set worker secrets, "
    "as well as get all template secrets. "
    "This will also report any secrets that don't match the template secret. "
    "This currently uses the following secrets: project/releng/docker-worker-secret",
)
@ciconfig_arguments(app)
@app.argument(
    "--update",
    action="store_true",
    help="Update existing worker secrets to match template.",
)
@run_async
async def create_worker_secrets(options):
    from .worker_secrets import create_worker_secrets

    await create_worker_secrets(update=options["update"])


@app.command(
    "generate-worker-pools",
    help="Generate the complete list of worker pools definitions.",
    description="This command expands the definied worker pools, "
    "by evaluating all the specifed variants. This does *not* expand the definitions "
    "to be useable by taskcluster (use `ci-admin generate` for that), but generates "
    "input suitable for ci-admin without variants.",
)
@ciconfig_arguments(app)
@format_arguments(app)
@app.argument("--grep", help="Regular expression to limit the worker pools listed.")
@run_async
async def generate_worker_pools(options):
    from .workers import generate_worker_pools

    await generate_worker_pools(
        grep=options["grep"],
        formatter=options["formatter"],
    )


@app.command("replay-hg-push", help="Retrigger the on-push tasks of an mercurial push")
@app.argument("alias", help="The project alias of the push to retrigger.")
@app.argument("revision", help="The tip revision of the push to retrigger.")
@ciconfig_arguments(app, use_environment=False)
@run_async
async def replay_hg_push(options):
    from .hg_pushes import replay_hg_push

    await replay_hg_push(alias=options["alias"], revision=options["revision"])


@app.command("list-workers")
@app.argument("worker-pool")
@app.argument(
    "--state",
    dest="states",
    action="append",
    choices=["requested", "running", "stopped"],
    help="List workers in the given states (can be given multiple times). "
    "[default: requested, running]",
)
@format_arguments(app)
def list_workers(options):
    from .workers import list_workers

    list_workers(
        options["worker-pool"],
        options["states"] or ["requested", "running"],
        formatter=options["formatter"],
    )


main = app.main
