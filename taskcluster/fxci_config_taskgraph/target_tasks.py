from taskgraph.target_tasks import register_target_task


@register_target_task("apply-staging")
def apply_staging(full_task_graph, parameters, graph_config):
    return ["tc-admin-apply-staging"]


@register_target_task("integration")
def integration(full_task_graph, parameters, graph_config):
    return [
        label
        for label, task in full_task_graph.tasks.items()
        if "integration" in task.attributes
    ]
