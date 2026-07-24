# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import os
import re
import sys

import click
from tcadmin import current
from tcadmin.appconfig import AppConfig
from tcadmin.main import main
from tcadmin.resources import Resources
from tcadmin.util.matchlist import MatchList

from ciadmin import modify
from ciadmin.generate import (
    clients,
    cron_tasks,
    git_pushes,
    grants,
    hg_pushes,
    hooks,
    in_tree_actions,
    scm_group_roles,
    worker_pools,
)

# Maps a --resources name to the module implementing it. Each module exposes
# `update_resources` (generate + manage) and a cheap, network-free
# `register_managed` (declare managed patterns only).
RESOURCES = {
    "clients": clients,
    "cron_tasks": cron_tasks,
    "git_pushes": git_pushes,
    "grants": grants,
    "hg_pushes": hg_pushes,
    "hooks": hooks,
    "in_tree_actions": in_tree_actions,
    "scm_group_roles": scm_group_roles,
    "worker_pools": worker_pools,
}

appconfig = AppConfig()

appconfig.options.add(
    "--environment",
    required=True,
    help="environment for which resources are to be generated",
)

appconfig.check_path = os.path.join(os.path.dirname(__file__), "check")

appconfig.modifiers.register(modify.modify_resources)

appconfig.description_prefix = (
    "*DO NOT EDIT* - This resource is configured automatically by "
    + "[ci-admin](https://github.com/mozilla-releng/fxci-config).\n\n"
)


# A managed pattern looks like `Kind=...`, optionally preceded by a negative
# lookahead (from `manage_with_exclusions`), e.g. `(?!Hook=proj-fuzzing/.*)Hook=.*`.
_KIND_RE = re.compile(r"(?:\(\?![^)]*\))?(\w+)=")


def _pattern_kinds(patterns):
    "Return the set of resource kinds (Role, Hook, ...) a list of patterns covers."
    kinds = set()
    for pattern in patterns:
        match = _KIND_RE.match(pattern)
        if match:
            kinds.add(match.group(1))
    return kinds


async def _collect_unselected_ownership(unselected, relevant_kinds):
    """
    Determine what the *unselected* generators own, so that a `--resources`
    subset diff can tell a genuine deletion (a resource owned only by a selected
    generator) from a resource that merely wasn't generated in this run because
    the generator that owns it was skipped.

    Ownership by managed pattern is not reliable: several generators declare
    broad catch-all patterns (e.g. hooks manages `Hook=.*`, grants manages
    `Role=hook-id:.*`) that also match resources *other* generators create. So
    for each unselected generator we use the ids it actually generates.

    Two shortcuts keep this cheap and decoupled:

    * We skip generators that cannot own any resource of the kinds being diffed
      (`relevant_kinds`, derived from what the selected generators fetch). E.g. a
      `--resources grants` diff never fetches WorkerPools, so worker_pools is not
      generated at all.
    * Generators whose generation needs network access (`REQUIRES_NETWORK`, i.e.
      in_tree_actions, which fetches `.taskcluster.yml` from every repo) would
      defeat the point of `--resources`, so we fall back to their (narrow, per
      trust domain) `register_managed` patterns instead of generating them.

    Returns a tuple of (owned ids, owned-pattern MatchList).
    """
    owned_ids = set()
    patterns = []
    for module in unselected:
        probe = Resources()
        await module.register_managed(probe)
        probe_patterns = list(probe.managed)
        if not (_pattern_kinds(probe_patterns) & relevant_kinds):
            # This generator can't own anything the current diff fetches.
            continue
        if getattr(module, "REQUIRES_NETWORK", False):
            patterns.extend(probe_patterns)
        else:
            tmp = Resources()
            await module.update_resources(tmp)
            owned_ids.update(r.id for r in tmp)
    return owned_ids, MatchList(patterns)


def _keep_current_resource(resource_id, generated_ids, owned_ids, owned_patterns):
    """
    Decide whether a current (live Taskcluster) resource should be kept when
    diffing a `--resources` subset.

    Keep it if we generated it ourselves (so real changes are compared), or if
    no unselected generator owns it (so a genuine deletion of a selected
    resource is still reported). Drop it only when an unselected generator owns
    it and we did not generate it -- that is a resource we simply skipped, not a
    deletion.
    """
    if resource_id in generated_ids:
        return True
    return not (resource_id in owned_ids or owned_patterns.matches(resource_id))


def _limit_diff_to_selected(resources_list):
    """
    Adjust `tc-admin`'s current-resource fetching so that a `--resources` subset
    diff/apply/current only considers resources the selected generators own.

    Registers a modifier that records the generated resource ids, and wraps
    `tcadmin.current.resources` to filter out live resources owned by the
    *unselected* generators. The (potentially expensive) ownership computation
    happens lazily inside that wrapper, so commands that never fetch current
    resources (e.g. `generate`) don't pay for it and aren't coupled to the
    health of unrelated generators.
    """
    unselected = [
        module for name, module in RESOURCES.items() if name not in resources_list
    ]
    state = {"generated_ids": set(), "ownership": None}

    async def capture_generated_ids(resources):
        state["generated_ids"] = {r.id for r in resources}
        return resources

    appconfig.modifiers.register(capture_generated_ids)

    original_current_resources = current.resources

    async def current_resources_excluding_unselected(managed):
        actual = await original_current_resources(managed)
        if state["ownership"] is None:
            state["ownership"] = await _collect_unselected_ownership(
                unselected, _pattern_kinds(managed)
            )
        owned_ids, owned_patterns = state["ownership"]
        kept = [
            r
            for r in actual
            if _keep_current_resource(
                r.id, state["generated_ids"], owned_ids, owned_patterns
            )
        ]
        return Resources(kept, actual.managed)

    current.resources = current_resources_excluding_unselected


def boot():
    if not os.environ.get("GITHUB_TOKEN") and not (
        os.environ.get("GITHUB_APP_ID") and os.environ.get("GITHUB_APP_PRIVKEY")
    ):
        click.echo(
            "WARNING: GITHUB_TOKEN is not present in the environment; you may run into rate limits querying for GitHub branches",
            err=True,
        )

    @click.command(
        context_settings={"ignore_unknown_options": True, "allow_extra_args": True}
    )
    @click.option(
        "--resources",
        required=False,
        default="all",
        help=f"Comma-separated list of resources to generate. Allowed values are: all,{','.join(RESOURCES.keys())}",
    )
    def register_resources_and_run(resources: str):
        resources_list = resources.split(",")
        if "all" in resources_list:
            for reso_module in RESOURCES.values():
                appconfig.generators.register(reso_module.update_resources)
        else:
            for reso in resources_list:
                if resource_module := RESOURCES.get(reso, None):
                    click.echo(f"Registering resource: {reso}", err=True)
                    appconfig.generators.register(resource_module.update_resources)
                else:
                    click.echo(f"Ignoring invalid resource: {reso}.", err=True)

            # The selected generators still declare broad managed patterns that
            # match resources owned by the generators we skipped; limit the diff
            # so those don't show up as spurious deletions.
            _limit_diff_to_selected(resources_list)

            if "clients" not in resources_list:
                from tcadmin.current import clients  # noqa: PLC0415

                async def fetch_clients(resources):
                    return

                clients.fetch_clients = fetch_clients

        # Remove the --resources arguments from sys.argv so inner "click.command"s don't complain
        # Handle parameter with =
        arg_regex = re.compile(r"^--resources\=.*")
        sys.argv = [arg for arg in sys.argv if not arg_regex.match(arg)]
        # Handle parameter with space
        while "--resources" in sys.argv:
            reso_arg_index = sys.argv.index("--resources")
            sys.argv = sys.argv[:reso_arg_index] + sys.argv[reso_arg_index + 2 :]

        main(appconfig)

    # if --help, then add the option to global and let main() handle it
    if "--help" in sys.argv:
        appconfig.options.add(
            "--resources",
            required=False,
            default="all",
            help=f"Comma-separated list of resources to generate. Allowed values are: all,{','.join(RESOURCES.keys())}",
        )
        main(appconfig)
    else:
        register_resources_and_run()
