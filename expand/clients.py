"""Expand compressed client definitions into flat Client resources.

Takes the parsed clients.yml and produces a dict of:
    {clientId: {"description": str, "scopes": [str, ...]}}
matching ciadmin's Client.fetch_all() format.
"""

import yaml

# Standard description prefix added by ciadmin
_DESC_PREFIX = "*DO NOT EDIT* - This resource is configured automatically.\n\n"


def _add_desc_prefix(desc):
    """Add the ciadmin auto-management prefix to a description."""
    return _DESC_PREFIX + desc


def _flatten_scopes(scopes):
    """Flatten a list of scopes that may contain nested lists from YAML anchors."""
    flat = []
    for item in scopes:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)
    return flat


def _expand_autophone(config, result):
    """Expand autophone-clients section."""
    auto_config = config.get("autophone-clients", {})
    for group_name, group in auto_config.items():
        base_scopes = group["base-scopes"]
        worker_id_prefix = group["worker-id-prefix"]
        for device in group["devices"]:
            name = device["name"]
            queue = device["queue"]
            desc = device.get("description", "")
            client_id = f"project/autophone/{name}"
            scopes = sorted(
                base_scopes
                + [
                    f"queue:claim-work:proj-autophone/{queue}",
                    f"queue:worker-id:{worker_id_prefix}/*",
                ]
            )
            result[client_id] = {
                "description": _add_desc_prefix(desc),
                "scopes": scopes,
            }


def _expand_scriptworker_k8s(config, result):
    """Expand scriptworker-k8s-clients section (standard pattern).

    Each entry produces a client with:
        client ID: project/releng/scriptworker/v2/{function}/{env}/firefoxci-{pool-group}
        scopes: queue:claim-work + queue:worker-id (derived from pool-group and function)
                plus any extra-scopes (which may contain YAML-anchor nested lists).
    """
    sw_config = config.get("scriptworker-k8s-clients", {})
    for function, envs in sw_config.items():
        for env, entries in envs.items():
            suffix = "-dev" if env == "dev" else ""
            for entry in entries:
                if isinstance(entry, str):
                    pool_group = entry
                    extra_scopes = []
                    desc = ""
                else:
                    pool_group = entry["pool-group"]
                    extra_scopes = _flatten_scopes(entry.get("extra-scopes", []))
                    desc = entry.get("description", "")

                client_id = (
                    f"project/releng/scriptworker/v2/{function}/{env}"
                    f"/firefoxci-{pool_group}"
                )
                worker_name = f"{pool_group}-{function}{suffix}"
                scopes = sorted(
                    [
                        f"queue:claim-work:scriptworker-k8s/{worker_name}",
                        f"queue:worker-id:{worker_name}/{worker_name}-*",
                    ]
                    + extra_scopes
                )
                result[client_id] = {
                    "description": _add_desc_prefix(desc),
                    "scopes": scopes,
                }


def _expand_scriptworker_explicit(config, result):
    """Expand scriptworker-explicit-clients section (custom scopes)."""
    explicit = config.get("scriptworker-explicit-clients", {})
    for client_id, props in explicit.items():
        scopes = _flatten_scopes(props.get("scopes", []))
        result[client_id] = {
            "description": _add_desc_prefix(props.get("description", "")),
            "scopes": sorted(scopes),
        }


def _expand_generic_worker(config, result):
    """Expand generic-worker-clients section."""
    gw_config = config.get("generic-worker-clients", {})
    for name, props in gw_config.items():
        client_id = f"project/releng/generic-worker/{name}"
        scopes = _flatten_scopes(props.get("scopes", []))
        result[client_id] = {
            "description": _add_desc_prefix(props.get("description", "")),
            "scopes": sorted(scopes),
        }


def _expand_single_scope_worker(config, result):
    """Expand single-scope-worker-clients section.

    Each entry is name: {description: str, worker-type: str}, producing
    exactly one assume:worker-type:{worker-type} scope.
    """
    ss_config = config.get("single-scope-worker-clients", {})
    for name, props in ss_config.items():
        client_id = f"project/releng/generic-worker/{name}"
        result[client_id] = {
            "description": _add_desc_prefix(props.get("description", "")),
            "scopes": [f"assume:worker-type:{props['worker-type']}"],
        }


def _expand_v3_mac_signing(config, result):
    """Expand v3-mac-signing-clients section.

    Each entry maps pool-group -> {description, extra-scopes?}.
    The pool-group determines the worker-type name:
      - If pool-group ends with '-3': worker-type = {product}-signing-mac14m2
      - If pool-group ends with '-t': worker-type = dep-{product}-signing-mac14m2
    Scopes are:
      assume:worker-type:scriptworker-prov-v1/{worker-type}
      queue:worker-id:{worker-type}/{worker-type}*
    Plus any extra-scopes.
    """
    v3_config = config.get("v3-mac-signing-clients", {})
    for pool_group, props in v3_config.items():
        if isinstance(props, str):
            desc = props
            extra_scopes = []
        else:
            desc = props.get("description", "")
            extra_scopes = _flatten_scopes(props.get("extra-scopes", []))

        # Derive product from pool-group (remove trailing -3 or -t)
        product = pool_group.rsplit("-", 1)[0]
        level_suffix = pool_group.rsplit("-", 1)[1]

        if level_suffix == "t":
            wt = f"dep-{product}-signing-mac14m2"
        else:
            wt = f"{product}-signing-mac14m2"

        client_id = (
            f"project/releng/scriptworker/v3/mac-signing/prod"
            f"/firefoxci-{pool_group}"
        )
        scopes = sorted(
            [
                f"assume:worker-type:scriptworker-prov-v1/{wt}",
                f"queue:worker-id:{wt}/{wt}*",
            ]
            + extra_scopes
        )
        result[client_id] = {
            "description": _add_desc_prefix(desc),
            "scopes": scopes,
        }


def _expand_oneoff(config, result):
    """Expand clients section (one-off clients)."""
    oneoff = config.get("clients", {})
    for client_id, props in oneoff.items():
        scopes = _flatten_scopes(props.get("scopes", []))
        result[client_id] = {
            "description": _add_desc_prefix(props.get("description", "")),
            "scopes": sorted(scopes),
        }


def expand_clients(config):
    """Expand compressed client config into flat dict.

    Args:
        config: Parsed YAML from clients.yml

    Returns:
        Dict of {clientId: {"description": str, "scopes": [str]}}
    """
    result = {}
    _expand_autophone(config, result)
    _expand_scriptworker_k8s(config, result)
    _expand_scriptworker_explicit(config, result)
    _expand_generic_worker(config, result)
    _expand_single_scope_worker(config, result)
    _expand_v3_mac_signing(config, result)
    _expand_oneoff(config, result)
    return result


def expand_clients_from_file(path="clients.yml"):
    """Load and expand clients from a YAML file."""
    with open(path) as f:
        config = yaml.safe_load(f)
    return expand_clients(config)
