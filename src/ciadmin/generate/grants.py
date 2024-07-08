# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import re

from tcadmin.resources import Role
from tcadmin.util.scopes import normalizeScopes

from ..util.matching import GroupGrantee, ProjectGrantee, RoleGrantee, project_match
from .ciconfig.environment import Environment
from .ciconfig.grants import Grant
from .ciconfig.projects import Project

LEVEL_PRIORITIES = {1: "low", 2: "low", 3: "highest"}


def job_to_role_suffix(job, pr_policy):
    # Normalize any `pull-request:` jobs to their appropriate role
    # suffix.
    if job == "pull-request:untrusted" and pr_policy == "public_restricted":
        return "pull-request-untrusted"
    elif job.startswith("pull-request"):
        return "pull-request"
    return job


def format_role_id(project, job, pr_policy):
    suffix = job_to_role_suffix(job, pr_policy)
    if project.role_prefix.endswith("*"):
        return project.role_prefix
    else:
        return "{}:{}".format(project.role_prefix, suffix)


def format_scope(project, scope, level, priority):
    # perform substitutions as grants.yml describes
    subs = {}
    subs["alias"] = project.alias
    if level:
        subs["level"] = level
    if priority:
        subs["priority"] = priority
    if project.trust_domain:
        subs["trust_domain"] = project.trust_domain
    if project.trust_project:
        subs["trust_project"] = project.trust_project

    try:
        subs["repo_path"] = project.repo_path
    except AttributeError:
        pass  # not an known supported repo..

    return scope.format(**subs)


def add_scopes_for_projects(grant, grantee, add_scope, projects):
    for project in projects:
        if not project_match(grantee, project):
            continue

        jobs = grantee.job

        # Force being explicit with pull-request policies. Otherwise, the `pull-request`
        # job would be equivalent to `pull-request:trusted`, which may not be intended.
        if "pull-request" in jobs:
            raise RuntimeError(
                "Invalid job 'pull-request'! Use 'pull-request:*' instead."
            )

        pr_policy = (project.feature("github-pull-request", key="policy") or "").strip()

        if "*" in jobs and project.repo_type == "git" and project.level != 1:
            # Github mixes pull-requests and other tasks under the same prefix
            # Since pull-requests should be level-1, we need to explicitly
            # split based on the job
            jobs = [job for job in jobs if job != "*"]
            jobs += [
                "pull-request:*",
                "branch:*",
                "cron:*",
                "action:*",
                "pr-action:*",
                "release:*",
            ]

        # Only grant scopes to `cron:` or `action:` jobs if the corresponding features
        # are enabled. This allows having generic grants that don't generate unused
        # roles
        if not project.feature("taskgraph-cron") and not project.feature("gecko-cron"):
            jobs = [job for job in jobs if not job.startswith("cron:")]
        if not project.feature("taskgraph-actions") and not project.feature(
            "gecko-actions"
        ):
            jobs = [job for job in jobs if not job.startswith("action:")]
        if not project.feature("pr-actions"):
            jobs = [job for job in jobs if not job.startswith("pr-action:")]

        # Only grant pull-request scopes where it makes sense.
        if (
            project.repo_type != "git"
            or not pr_policy
            or not grantee.include_pull_requests
        ):
            jobs = [
                job
                for job in jobs
                if not job.startswith("pull-request")
                and not job.startswith("pr-action")
            ]

        if "pull-request:*" in jobs:
            jobs.remove("pull-request:*")
            jobs.extend(["pull-request:trusted", "pull-request:untrusted"])

        # Remove any 'pull-request:trusted' jobs for projects using the 'public' policy.
        # Similarly, remove any 'pull-request:untrusted' jobs for projects using the
        # 'collaborators' policy. Only the 'public_restricted' policy supports both at
        # the same time.
        if pr_policy == "public":
            jobs = [job for job in jobs if job != "pull-request:trusted"]
        elif pr_policy.startswith("collaborators"):
            jobs = [job for job in jobs if job != "pull-request:untrusted"]

        # ok, this project matches!
        for job in jobs:
            roleId = format_role_id(project, job, pr_policy)
            level = project.get_level()
            # This is explicitly fetched before we override level for pull
            # requests due to us granting them `highest` priority in the past.
            # Ideally we'd stop doing this, but it requires all GitHub repositories
            # to start using a different priority for their PR tasks before
            # we can do so.
            priority = LEVEL_PRIORITIES[level]
            # In order to avoid granting pull-requests graphs
            # access to the level-3 workers, we overwrite their value here
            if level is not None and (
                job.startswith("pull-request") or job.startswith("pr-action")
            ):
                level = 1

            for scope in grant.scopes:
                add_scope(roleId, format_scope(project, scope, level, priority))


def add_scopes_for_groups(grant, grantee, add_scope):
    for group in grantee.groups:
        roleId = "project:releng:ci-group:{}".format(group)
        for scope in grant.scopes:
            # use an empty format() to catch any stray {..} in the scope
            add_scope(roleId, scope.format())


def add_scopes_for_roles(grant, grantee, add_scope):
    for role in grantee.roles:
        for scope in grant.scopes:
            # use an empty format() to catch any stray {..} in the scope
            add_scope(role, scope.format())


async def update_resources(resources):
    """
    Manage the scopes granted to projects.  This file interprets `grants.yml`
    in ci-configuration. Its behavior is largely documented in the comment in that file.
    """

    grants = await Grant.fetch_all()
    projects = await Project.fetch_all()
    environment = await Environment.current()

    # manage our resources..
    resources.manage("Role=mozilla-group:.*")
    resources.manage("Role=mozillians-group:.*")
    resources.manage("Role=login-identity:.*")
    resources.manage("Role=hook-id:.*")
    resources.manage("Role=project:.*")
    resources.manage("Role=repo:.*")

    # calculate scopes..
    roles = {}

    def add_scope(roleId, scope):
        roles.setdefault(roleId, []).append(scope)

    for grant in grants:
        if grant.environments and environment.name not in grant.environments:
            # skip grant for this environment
            continue
        for grantee in grant.grantees:
            if isinstance(grantee, ProjectGrantee):
                add_scopes_for_projects(grant, grantee, add_scope, projects)
            elif isinstance(grantee, GroupGrantee):
                add_scopes_for_groups(grant, grantee, add_scope)
            elif isinstance(grantee, RoleGrantee):
                add_scopes_for_roles(grant, grantee, add_scope)
            else:
                raise RuntimeError("unknown grantee!")

    # ..and add the roles
    for roleId, scopes in roles.items():
        resources.manage("Role={}".format(re.escape(roleId)))
        role = Role(
            roleId=roleId,
            scopes=normalizeScopes(scopes),
            description="Scopes in this role are defined in "
            "[ci-configuration/grants.yml]"
            "(https://hg.mozilla.org/ci/ci-configuration/file/tip/grants.yml).",
        )
        resources.add(role)
