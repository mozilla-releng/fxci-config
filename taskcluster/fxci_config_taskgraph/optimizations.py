import os
import subprocess
from functools import cache
from pprint import pformat

from taskgraph.optimize.base import OptimizationStrategy, register_strategy
from taskgraph.optimize.strategies import SkipUnlessChanged, logger

from fxci_config_taskgraph.util.constants import FIREFOXCI_ROOT_URL


@register_strategy("integration-test")
class IntegrationTestStrategy(OptimizationStrategy):
    @cache
    def _get_modified_worker_pools(self) -> set[str]:
        cmd = [
            "uv",
            "tool",
            "run",
            "--with",
            os.getcwd(),
            "tc-admin",
            "diff",
            "--environment",
            "firefoxci",
            "--resources",
            "worker_pools",
            "--ids-only",
        ]
        env = os.environ.copy()
        env["TASKCLUSTER_ROOT_URL"] = FIREFOXCI_ROOT_URL
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, env=env)
        lines = [line for line in proc.stdout.splitlines() if line.startswith("!")]

        worker_pools = set()
        for line in lines:
            line = line.split()[1]
            assert line.startswith("WorkerPool=")
            line = line.split("=", 1)[1]
            worker_pools.add(line)

        logger.debug(f"Modified worker pools:\n{pformat(worker_pools)}")
        return worker_pools

    def should_remove_task(self, task, params, files_changed):
        task_queue_id = f"{task.task['provisionerId']}/{task.task['workerType']}"
        if task_queue_id in self._get_modified_worker_pools():
            return False

        # If the worker type wasn't impacted, defer to `skip-unless-changed`.
        opt = SkipUnlessChanged()
        return opt.should_remove_task(task, params, files_changed)
