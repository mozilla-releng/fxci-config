import copy

from taskgraph.transforms.base import TransformSequence
from taskgraph.util.schema import Schema
from voluptuous import Extra, Optional, Required

schema = Schema(
    {
        Required("description"): str,
        Required("name"): str,
        Optional("environments"): [str],
        Extra: object,
    }
)

transforms = TransformSequence()
transforms.add_validate(schema)


@transforms.add
def split_environment(config, tasks):
    for task in tasks:
        for environment in task.pop("environments", ["firefoxci"]):
            new_task = copy.deepcopy(task)
            new_task["name"] = f"{new_task['name']}-{environment}"
            new_task["description"] = new_task["description"].format(
                environment=environment
            )

            worker = new_task.setdefault("worker", {})
            env = worker.setdefault("env", {})
            env["ENVIRONMENT"] = environment
            yield new_task
