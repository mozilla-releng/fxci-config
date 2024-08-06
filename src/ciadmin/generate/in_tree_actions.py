# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import asyncio
import datetime
import functools
import hashlib
import textwrap

import aiohttp
import iso8601
import yaml
from taskcluster import optionsFromEnvironment
from taskcluster.aio import Hooks
from taskcluster.exceptions import TaskclusterRestFailure
from tcadmin.resources import Hook, Role
from tcadmin.util.matchlist import MatchList
from tcadmin.util.scopes import normalizeScopes
from tcadmin.util.sessions import aiohttp_session

from . import tcyml
from .ciconfig.actions import Action
from .ciconfig.projects import Project

# Any existing hooks that no longer correspond to active .taskcluster.yml files
# will nonetheless be kept around until this time has passed since they were
# last fired.  This ensures that any "popular" hooks stick around, for example
# to support try jobs run against old revisions.
HOOK_RETENTION_TIME = datetime.timedelta(days=60)


async def hash_taskcluster_ymls():
    """
    Download and hash .taskcluster.yml from every project repository.  Returns
    {alias: (parsed content, hash)}.
    """
    projects = await Project.fetch_all()

    def should_hash(project):
        if project.feature("gecko-actions"):
            if not project.feature("hg-push") and not project.feature("gecko-cron"):
                return False
            if project.is_try:
                return False
            return True
        elif project.feature("taskgraph-actions"):
            return True
        else:
            return False

    # hash the value of this .taskcluster.yml.  Note that this must match the
    # hashing in taskgraph/actions/registry.py
    def hash(val):
        return hashlib.sha256(val).hexdigest()[:10]

    tcyml_projects = list(filter(should_hash, projects))
    futures = []
    rv = {}
    for p in tcyml_projects:
        rv[p.alias] = {}

        for b in set([b.name for b in p.branches] + [p.default_branch]):
            # Can't fetch a .taskcluster.yml for a globbed branch
            # TODO: perhaps we should do this for partly globbed branches,
            # eg: release* ?
            # we'd have to fetch that list from the server to do that
            if "*" not in b and "*" not in p.repo:

                def process(project, branch_name, task):
                    try:
                        tcy = task.result()
                    except aiohttp.ClientResponseError as e:
                        # .taskcluster.yml doesn't exist. This can happen if
                        # a project owner moves it away to disable Taskcluster.
                        if e.status == 404:
                            return
                        raise e

                    # some ancient projects have no .taskcluster.yml
                    if not tcy:
                        return

                    # some old projects have .taskcluster.yml's that are not valid YAML
                    # (back in the day, mozilla-taskcluster used mustache to templatize
                    # the text before parsing it..). Ignore those projects.
                    try:
                        parsed = yaml.safe_load(tcy)
                    except Exception:
                        return

                    # some slightly less old projects have
                    # {tasks: $let: .., in: [..]} instead of the expected
                    # {tasks: [{$let: .., in: ..}]}.  Those can be ignored too.
                    if not isinstance(parsed["tasks"], list):
                        return

                    rv[project.alias][branch_name] = {
                        "parsed": parsed,
                        "hash": hash(tcy),
                        "level": project.get_level(branch_name),
                        "alias": project.alias,
                    }

                future = asyncio.ensure_future(
                    tcyml.get(p.repo, repo_type=p.repo_type, default_branch=b)
                )
                future.add_done_callback(functools.partial(process, p, b))
                futures.append(future)

    await asyncio.gather(*futures, return_exceptions=True)
    return rv


def make_hook(action, tcyml_content, tcyml_hash, projects, pr=False):
    hookGroupId = f"project-{action.trust_domain}"
    hookId = "in-tree-{}action-{}-{}/{}".format(
        "pr-" if pr else "", action.level, action.action_perm, tcyml_hash
    )

    # making matching project list for description field

    matching_projects = []
    for project in projects.values():
        for branch in project:
            if project[branch]["hash"] == tcyml_hash and str(action.level) == str(
                project[branch]["level"]
            ):
                matching_projects.append(
                    f"{project[branch]['alias']}, branch: '{branch}'"
                )

    # schema-generation utilities

    def obj(_description=None, *, optional=(), **properties):
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": sorted(properties.keys() - optional),
            "properties": properties,
        }
        if _description:
            schema["description"] = _description
        return schema

    def prop(description, type="string", **extra):
        return dict(description=description, type=type, **extra)

    # The triggerSchema describes the input to the hook. This is provided by
    # the hookPayload template in the actions.json file generated in-tree, and
    # is divided nicely into information from the decision task and information
    # about the user's action request.
    trigger_schema = obj(
        textwrap.dedent(
            """Information required to trigger this hook.  This is provided by the
            `hookPayload` template in the `actions.json` file generated in-tree."""
        ),
        decision=obj(
            textwrap.dedent(
                """Information provided by the decision task; this is usually baked into
            `actions.json`, although any value could be supplied in a direct call to
            `hooks.triggerHook`."""
            ),
            action=obj(
                "Information about the action to perform",
                name=prop("action name"),
                title=prop("action title"),
                description=prop("action description"),
                taskGroupId=prop("taskGroupId of the decision task"),
                cb_name=prop("name of the in-tree callback function"),
                symbol=prop("treeherder symbol"),
            ),
            push=obj(
                "Information about the push that created the decision task",
                owner=prop("user who made the original push"),
                revision=prop("revision of the original push"),
                base_revision=prop("revision before the push occurred"),
                pushlog_id=prop("Mercurial pushlog ID of the original push"),
                branch=prop("branch revision of original push is from"),
                base_branch=prop("branch this pull request is based on, if applicable"),
                # TODO Make "base_revision" mandatory once all repositories are
                # on taskgraph 3.0+
                optional={"base_revision", "branch", "base_branch"},
            ),
            repository=obj(
                "Information about the repository where the push occurred",
                url=prop("repository URL (without trailing slash)", pattern="[^/]$"),
                project=prop('repository project name (also known as "alias")'),
                level=prop("repository SCM level"),
                base_url=prop(
                    "repository URL to use when checking scopes for this action"
                ),
                optional={"base_url"},
            ),
            parameters={
                "type": "object",
                "description": "decision task parameters",
                "additionalProperties": True,
            },
            optional={"parameters"},
        ),
        user=obj(
            "Information provided by the user or user interface",
            input=action.input_schema,
            taskId={
                "anyOf": [
                    prop("taskId of the task on which this action was activated"),
                    {
                        "const": None,
                        "description": "null when the action is activated for "
                        "a taskGroup",
                    },
                ]
            },
            taskGroupId=prop("taskGroupId on which this task was activated"),
        ),
    )

    if pr:
        scope_repo_location = "payload.decision.repository.base_url"
    else:
        scope_repo_location = "payload.decision.repository.url"

    # Given a JSON-e context value `payload` matching the above trigger schema,
    # as well as the `taskId` provided by the hooks service (giving the taskId
    # of the new task), the following JSON-e template rearranges the provided
    # values and supplies them as context to an embedded `.taskclsuter.yml`.
    # This context format is what `.taskcluster.yml` expects, and is based on
    # that provided by mozilla-taskcluster.

    # If this changes, we likely also need to change the corresponding logic in
    # scriptworker.cot.verify._wrap_action_hook_with_let
    # https://github.com/mozilla-releng/scriptworker/search?q=_wrap_action_hook_with_let
    task = {
        "$let": {
            "tasks_for": "{}action".format("pr-" if pr else ""),
            "action": {
                "name": "${payload.decision.action.name}",
                "title": "${payload.decision.action.title}",
                "description": "${payload.decision.action.description}",
                "taskGroupId": "${payload.decision.action.taskGroupId}",
                "symbol": "${payload.decision.action.symbol}",
                "cb_name": "${payload.decision.action.cb_name}",
                # Calculated repo_scope.  This is based on user input (the repository),
                # but the hooks service checks that this is satisfied by the
                # `hook-id:<hookGroupId>/<hookId>` role, which is set up above to only
                # contain scopes for repositories at this level. Note that the
                # action_perm is *not* based on user input, but is fixed in the
                # hookPayload template.  We would like to get rid of this parameter and
                # calculate it directly in .taskcluster.yml, once all the other work
                # for actions-as-hooks has finished
                "repo_scope": "assume:repo:"
                "${" + scope_repo_location + "[8:]}:action:" + action.action_perm,
                "action_perm": action.action_perm,
            },
            # remaining sections are copied en masse from the hook payload
            "push": {"$eval": "payload.decision.push"},
            "repository": {"$eval": "payload.decision.repository"},
            "input": {"$eval": "payload.user.input"},
            "parameters": {"$eval": "payload.decision['parameters']"},
            # taskId and taskGroupId represent the task and/or task group
            # the user has targetted with this action
            "taskId": {"$eval": "payload.user.taskId"},
            "taskGroupId": {"$eval": "payload.user.taskGroupId"},
            # the hooks service provides the taskId that it will use for
            # the resulting action task
            "ownTaskId": {"$eval": "taskId"},
        },
        "in": tcyml_content["tasks"][0],
    }

    return Hook(
        hookGroupId=hookGroupId,
        hookId=hookId,
        name=f"{hookGroupId}/{hookId}",
        description=textwrap.dedent(
            """\
            {}ction task {} at level {}, with `.taskcluster.yml` hash {}.

            For (project, branch) combinations:
            {}

            This hook is fired in response to actions defined in a
            Gecko decision task's `actions.json`.
            """
        ).format(
            "PR a" if pr else "A",
            action.action_perm,
            action.level,
            tcyml_hash,
            "\n".join(matching_projects),
        ),
        owner="taskcluster-notifications@mozilla.com",
        emailOnError=True,
        schedule=[],
        bindings=[],
        task=task,
        triggerSchema=trigger_schema,
    )


async def update_resources(resources):
    """
    Manage the hooks and accompanying hook-id:.. roles for in-tree actions.
    """
    hashed_tcymls = await hash_taskcluster_ymls()
    actions = await Action.fetch_all()
    projects = await Project.fetch_all()
    projects = [
        p
        for p in projects
        if p.feature("gecko-actions") or p.feature("taskgraph-actions")
    ]

    # manage the in-tree-action-* hooks, and corresponding roles, for each trust domain
    trust_domains = set(action.trust_domain for action in actions)
    for trust_domain in trust_domains:
        resources.manage(f"Hook=project-{trust_domain}/in-tree-action-.*")
        resources.manage(f"Role=hook-id:project-{trust_domain}/in-tree-action-.*")
        resources.manage(f"Hook=project-{trust_domain}/in-tree-pr-action-.*")
        resources.manage(f"Role=hook-id:project-{trust_domain}/in-tree-pr-action-.*")

    projects_by_level_and_trust_domain = {}
    for project in projects:
        for branch in project.branches:
            projects_by_level_and_trust_domain.setdefault(
                (project.trust_domain, project.get_level(branch.name)), []
            ).append(project)

    # generate the hooks themselves and corresponding hook-id roles
    added_hooks = set()
    for action in actions:
        # gather the hashes at the action's level or higher
        hooks_to_make = {}  # {hash: content}, for uniqueness
        for project in projects:
            for branch_name in set(
                [b.name for b in project.branches] + [project.default_branch]
            ):
                # We don't have taskcluster.ymls from globbed branches;
                # see comment in hash_taskcluster_ymls
                if "*" in branch_name:
                    continue
                if project.alias not in hashed_tcymls:
                    continue
                if project.get_level(branch_name) < action.level:
                    continue
                if project.trust_domain != action.trust_domain:
                    continue
                if branch_name not in hashed_tcymls[project.alias]:
                    # Branch didn't exist, or doesn't have a parseable tcyml
                    continue

                content, hash = (
                    hashed_tcymls[project.alias][branch_name]["parsed"],
                    hashed_tcymls[project.alias][branch_name]["hash"],
                )
                hooks_to_make[hash] = content

        for hash, content in hooks_to_make.items():
            hook = make_hook(action, content, hash, hashed_tcymls)
            resources.add(hook)
            added_hooks.add(hook.id)
            if action.level == 1 and any(
                p.feature("pr-actions")
                for p in projects
                if p.trust_domain == action.trust_domain
            ):
                hook = make_hook(action, content, hash, hashed_tcymls, True)
                resources.add(hook)
                added_hooks.add(hook.id)

        # use a single, star-suffixed role for all hashed versions of a hook
        role = Role(
            roleId=f"hook-id:project-{action.trust_domain}/in-tree-action-{action.level}-{action.action_perm}/*",
            description=f"Scopes associated with {action.trust_domain} action `{action.action_perm}` "
            f"on each repo at level {action.level}",
            scopes=normalizeScopes(
                [
                    f"assume:{p.role_prefix}:action:{action.action_perm}"
                    for p in projects_by_level_and_trust_domain.get(
                        (action.trust_domain, action.level), []
                    )
                ]
            ),
        )
        resources.add(role)
        if action.level == 1 and any(
            p.feature("pr-actions")
            for p in projects
            if p.trust_domain == action.trust_domain
        ):
            role = Role(
                roleId=f"hook-id:project-{action.trust_domain}/in-tree-pr-action-{action.level}-{action.action_perm}/*",
                description=f"Scopes associated with {action.trust_domain} PR action `{action.action_perm}` "
                f"on each repo at level {action.level}",
                scopes=normalizeScopes(
                    [
                        f"assume:{p.role_prefix}:pr-action:{action.action_perm}"
                        for p in projects
                        if p.feature("pr-actions")
                        and p.trust_domain == action.trust_domain
                    ]
                ),
            )
            resources.add(role)

    # download all existing hooks and check the last time they were used
    hooks = Hooks(optionsFromEnvironment(), session=aiohttp_session())
    interesting = MatchList(
        f"Hook=project-{trust_domain}/in-tree-action-*"
        for trust_domain in trust_domains
    )
    for trust_domain in trust_domains:
        hookGroupId = f"project-{trust_domain}"
        try:
            res = await hooks.listHooks(hookGroupId)
        except TaskclusterRestFailure as e:
            if e.status_code != 404:
                raise e
            # if the group doesn't exist, that's OK, it just means there are no hooks.
            continue

        for hook in res["hooks"]:
            hook = Hook.from_api(hook)
            # ignore if this is not an in-tree-action hook
            if not interesting.matches(hook.id):
                continue

            # ignore if we've already generated this hook
            if hook.id in added_hooks:
                continue

            # ignore if the hook has never been fired
            hookStatus = await hooks.getHookStatus(hook.hookGroupId, hook.hookId)
            if "lastFire" not in hookStatus or "time" not in hookStatus["lastFire"]:
                continue

            # ignore if it's too old; do the arithmetic in days to avoid timezone issues
            last = iso8601.parse_date(hookStatus["lastFire"]["time"])
            age = datetime.date.today() - last.date()
            if age > HOOK_RETENTION_TIME:
                continue

            # we want to keep this hook, so we add it to the "generated"
            # resources, ensuring it does not get deleted.
            if "for historical purposes" not in hook.description:
                description = (
                    hook.description
                    + "\n\nThis hook is no longer current and is kept for "
                    "historical purposes."
                )
                hook = hook.evolve(description=description)
            resources.add(hook)
