import os
from importlib import import_module

import taskgraph.util.verify

from .util.constants import STAGING_ROOT_URL


def register(graph_config):
    """Setup for task generation."""

    # Import sibling modules, triggering decorators in the process
    _import_modules(
        [
            "optimizations",
            "target_tasks",
        ]
    )

    if os.environ["TASKCLUSTER_ROOT_URL"] == STAGING_ROOT_URL:
        # Disable verify_run_task_caches because it gets confused by our command mangling
        full_verifications = taskgraph.util.verify.verifications._verifications[
            "full_task_graph"
        ]
        full_verifications = [
            v for v in full_verifications if v.func.__name__ != "verify_run_task_caches"
        ]
        taskgraph.util.verify.verifications._verifications["full_task_graph"] = (
            full_verifications
        )


def _import_modules(modules):
    for module in modules:
        import_module(f".{module}", package=__name__)
