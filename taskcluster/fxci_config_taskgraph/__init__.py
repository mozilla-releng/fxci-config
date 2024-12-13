from importlib import import_module


def register(graph_config):
    """Setup for task generation."""

    # Import sibling modules, triggering decorators in the process
    _import_modules(
        [
            "optimizations",
            "target_tasks",
        ]
    )


def _import_modules(modules):
    for module in modules:
        import_module(f".{module}", package=__name__)
