# fxci-config expansion layer

"""Expand normalized config and inject into ciadmin's config cache.

Reads: pool-groups.yml, worker-pools.yml, clients.yml, projects.yml
Injects into: ciadmin.generate.ciconfig.get._cache
"""
import yaml

from expand.pool_groups import load_pool_groups_from_file
from expand.validate_schema import validate_schemas
from expand.worker_pools import expand_worker_pools
from expand.clients import expand_clients_from_file
from expand.projects import expand_projects


def expand_all():
    # Validate schemas before expansion
    schema_errors = validate_schemas()
    if schema_errors:
        raise ValueError(
            f"Schema validation failed with {len(schema_errors)} error(s):\n"
            + "\n".join(f"  {e}" for e in schema_errors)
        )

    pool_groups = load_pool_groups_from_file("pool-groups.yml")

    # Expand worker pools
    with open("worker-pools.yml") as f:
        wp_config = yaml.safe_load(f)
    expanded_pools = expand_worker_pools(wp_config, pool_groups)

    # Expand clients
    expanded_clients = expand_clients_from_file("clients.yml")

    # Expand projects
    with open("projects.yml") as f:
        pj_config = yaml.safe_load(f)
    expanded_projects = expand_projects(pj_config)

    # Inject into ciadmin's config cache
    from ciadmin.generate.ciconfig import get
    get._cache["worker-pools.yml"] = {
        "worker-defaults": wp_config.get("worker-defaults-passthrough", {}),
        "pool-templates": {},
        "pools": expanded_pools,
    }
    get._cache["clients.yml"] = expanded_clients
    get._cache["clients-interpreted.yml"] = []
    get._cache["projects.yml"] = expanded_projects
