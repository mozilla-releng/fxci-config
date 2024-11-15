from taskgraph.target_tasks import register_target_task


@register_target_task("apply-staging")
def apply_staging(full_task_graph, parameters, graph_config):
    return ["tc-admin-apply-staging"]
