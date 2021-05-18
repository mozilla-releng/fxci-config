# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from tcadmin.util.root_url import root_url

from ciadmin.generate.ciconfig.environment import Environment

MODIFIERS = {}


def modifier(fn):
    MODIFIERS[fn.__name__] = fn
    return fn


@modifier
def remove_hook_schedules(resources):
    """
    Remove schedules from all managed hooks, so that they do not run and create tasks.
    """

    def modify(resource):
        if resource.kind != "Hook":
            return resource
        if not resource.schedule:
            return resource
        return resource.evolve(schedule=[])

    return resources.map(modify)


@modifier
def remove_hook_bindings(resources):
    """
    Remove bindings from all managed hooks, so that they do not try to listen
    to exchanges that do not exist.
    """

    def modify(resource):
        if resource.kind != "Hook":
            return resource
        if not resource.bindings:
            return resource
        return resource.evolve(bindings=[])

    return resources.map(modify)


@modifier
def remove_worker_min_capacity(resources):
    """
    Remove minimum capacity of all worker-types, since staging clusters
    do not have enough load to justify always-on workers.
    """

    def modify(resource):
        if resource.kind != "WorkerPool":
            return resource
        # some worker pool types (like "static") don't support capacity
        if "minCapacity" not in resource.config:
            return resource
        resource.config["minCapacity"] = 0
        return resource

    return resources.map(modify)


async def modify_resources(resources):
    """
    Apply any `modify_resources` functions to the given resources, as determined
    by the ciconfig `environments.yml` file, and return a new set of resources.
    """
    environment = await Environment.current()

    # sanity-check, to prevent applying to the wrong Taskcluster instance, allowing
    # for the presence or absence of trailing `/` to avoid user inconvenience.
    if root_url().rstrip("/") != environment.root_url.rstrip("/"):
        raise RuntimeError(
            "Environment {} expects rootUrl {}"
            ", but active credentials are for {}".format(
                environment.name, environment.root_url, root_url()
            )
        )

    for mod in environment.modify_resources:
        if mod not in MODIFIERS:
            raise KeyError("No modify_resources function named {}".format(mod))
        resources = MODIFIERS[mod](resources)
    return resources
