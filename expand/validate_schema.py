"""Schema validation for fxci-config YAML files.

Validates pool-groups.yml, worker-pools.yml, clients.yml, and projects.yml
BEFORE expansion, catching structural errors and typos early with clear
error messages.
"""

import difflib
import sys

import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _suggest(name, valid_names, n=3, cutoff=0.6):
    """Return 'did you mean' suggestions using difflib."""
    matches = difflib.get_close_matches(name, valid_names, n=n, cutoff=cutoff)
    if matches:
        suggestions = ", ".join(f"'{m}'" for m in matches)
        return f" (did you mean {suggestions}?)"
    return ""


def _check_unknown_fields(data, known_fields, path, filename, errors, severity="warn"):
    """Check for unknown fields in a dict, adding warnings or errors."""
    if not isinstance(data, dict):
        return
    for key in data:
        if key not in known_fields:
            suggestion = _suggest(key, known_fields)
            msg = f"{filename}: {path}: unknown field '{key}'{suggestion}"
            if severity == "error":
                errors.append(msg)
            else:
                errors.append(msg)


def _require_fields(data, required_fields, path, filename, errors):
    """Check that required fields are present."""
    if not isinstance(data, dict):
        return
    for field in required_fields:
        if field not in data:
            errors.append(f"{filename}: {path}: missing required field '{field}'")


# ---------------------------------------------------------------------------
# pool-groups.yml
# ---------------------------------------------------------------------------

_POOL_GROUP_ENTRY_KNOWN = {"levels", "testing"}


def validate_pool_groups(config, filename="pool-groups.yml"):
    """Validate pool-groups.yml structure.

    Returns a list of error/warning strings (empty means valid).
    """
    errors = []

    if not isinstance(config, dict):
        errors.append(f"{filename}: top-level must be a dict")
        return errors

    if "pool-groups" not in config:
        errors.append(f"{filename}: missing required key 'pool-groups'")
        return errors

    pg = config["pool-groups"]
    if not isinstance(pg, dict):
        errors.append(f"{filename}: 'pool-groups' must be a dict")
        return errors

    for name, entry in pg.items():
        path = f"pool-groups.{name}"
        if not isinstance(entry, dict):
            errors.append(f"{filename}: {path}: must be a dict")
            continue

        if "levels" not in entry:
            errors.append(f"{filename}: {path}: missing required field 'levels'")
        else:
            levels = entry["levels"]
            if not isinstance(levels, list):
                errors.append(f"{filename}: {path}.levels: must be a list")
            else:
                for i, level in enumerate(levels):
                    if level != "standalone" and not isinstance(level, int):
                        errors.append(
                            f"{filename}: {path}.levels[{i}]: must be int or 'standalone', got {level!r}"
                        )

        if "testing" in entry and not isinstance(entry["testing"], bool):
            errors.append(f"{filename}: {path}.testing: must be a bool")

        _check_unknown_fields(entry, _POOL_GROUP_ENTRY_KNOWN, path, filename, errors)

    return errors


# ---------------------------------------------------------------------------
# worker-pools.yml
# ---------------------------------------------------------------------------

_WP_TOP_LEVEL_KNOWN = {
    "pools", "defaults", "worker-defaults-passthrough", "templates",
    "machines", "azure-shared", "group-aliases",
}

_WP_POOL_KNOWN = {
    "pool_id", "template", "groups", "suffixes", "description", "owner",
    "email_on_error", "provider_id", "machine", "machine-override", "cloud",
    "implementation", "worker-purpose", "provider", "maxCapacity", "minCapacity",
    "capacityPerInstance", "regions", "image", "image_resource_group",
    "worker-config", "locations", "vm_size", "armDeployment", "tags",
    "worker-manager-config", "spot", "managed_disk", "disk_controller_type",
    "nvme_placement", "caching", "ephemeral_disk",
}


def _validate_wp_pool_entry(entry, idx, templates, machines, pool_group_names, filename, errors):
    """Validate a single pool entry in the pools list."""
    path = f"pools[{idx}]"

    if not isinstance(entry, dict):
        errors.append(f"{filename}: {path}: must be a dict")
        return

    # Check for pool-table or pool-pair (compound entries)
    if "pool-table" in entry:
        _validate_pool_table(entry["pool-table"], idx, filename, errors)
        return
    if "pool-pair" in entry:
        _validate_pool_pair(entry["pool-pair"], idx, filename, errors)
        return

    # Regular pool entry
    if "pool_id" not in entry:
        errors.append(f"{filename}: {path}: missing required field 'pool_id'")

    # Warn on unknown fields
    for key in entry:
        if key not in _WP_POOL_KNOWN:
            suggestion = _suggest(key, _WP_POOL_KNOWN)
            errors.append(f"{filename}: {path}: unknown field '{key}'{suggestion}")

    # Validate template reference
    if "template" in entry and templates is not None:
        tmpl = entry["template"]
        if isinstance(tmpl, str) and tmpl not in templates:
            suggestion = _suggest(tmpl, list(templates.keys()))
            errors.append(
                f"{filename}: {path}.template: references unknown template '{tmpl}'{suggestion}"
            )

    # Validate machine reference
    if "machine" in entry and machines is not None:
        machine = entry["machine"]
        if isinstance(machine, str) and not machine.startswith("by-") and machine not in machines:
            # Could be an inline machine type (not in presets) -- only warn if it
            # looks like it could be a preset name (contains letters and dashes)
            suggestion = _suggest(machine, list(machines.keys()))
            if suggestion:
                errors.append(
                    f"{filename}: {path}.machine: unknown machine preset '{machine}'{suggestion}"
                )

    # Validate groups references
    if "groups" in entry and pool_group_names is not None:
        groups = entry["groups"]
        if isinstance(groups, list):
            _validate_groups_list(groups, f"{path}.groups", pool_group_names, filename, errors)


def _validate_groups_list(groups, path, pool_group_names, filename, errors):
    """Validate a groups list, checking that each entry references a valid pool-group or trust-domain."""
    # Extract trust domains from pool group names
    trust_domains = set()
    for pg_name in pool_group_names:
        parts = pg_name.rsplit("-", 1)
        if len(parts) == 2:
            trust_domains.add(parts[0])
        else:
            trust_domains.add(pg_name)

    valid_names = set(pool_group_names) | trust_domains

    for i, entry in enumerate(groups):
        if isinstance(entry, str):
            if entry.startswith("@"):
                continue  # alias, validated elsewhere
            if entry not in valid_names:
                suggestion = _suggest(entry, list(valid_names))
                errors.append(
                    f"{filename}: {path}[{i}]: unknown pool-group or trust-domain '{entry}'{suggestion}"
                )
        # dict entries (trust-domain overrides) are valid structural forms


def _validate_pool_table(table, idx, filename, errors):
    """Validate a pool-table entry."""
    path = f"pools[{idx}].pool-table"

    if not isinstance(table, dict):
        errors.append(f"{filename}: {path}: must be a dict")
        return

    if "columns" not in table:
        errors.append(f"{filename}: {path}: missing required field 'columns'")
    if "rows" not in table:
        errors.append(f"{filename}: {path}: missing required field 'rows'")

    if "columns" in table and "rows" in table:
        columns = table["columns"]
        rows = table["rows"]
        if isinstance(columns, list) and isinstance(rows, list):
            for i, row in enumerate(rows):
                if isinstance(row, list) and len(row) != len(columns):
                    errors.append(
                        f"{filename}: {path}.rows[{i}]: has {len(row)} values "
                        f"but {len(columns)} columns defined"
                    )


def _validate_pool_pair(pair, idx, filename, errors):
    """Validate a pool-pair entry."""
    path = f"pools[{idx}].pool-pair"

    if not isinstance(pair, dict):
        errors.append(f"{filename}: {path}: must be a dict")
        return

    if "variants" not in pair:
        errors.append(f"{filename}: {path}: missing required field 'variants'")
    elif not isinstance(pair["variants"], list):
        errors.append(f"{filename}: {path}.variants: must be a list")


def _validate_template_extends(templates, filename, errors):
    """Validate template extends chains: targets exist and no circular chains."""
    if not templates:
        return

    for name, tmpl in templates.items():
        if not isinstance(tmpl, dict):
            continue
        if "extends" in tmpl:
            target = tmpl["extends"]
            if isinstance(target, str) and target not in templates:
                suggestion = _suggest(target, list(templates.keys()))
                errors.append(
                    f"{filename}: templates.{name}.extends: "
                    f"references unknown template '{target}'{suggestion}"
                )

    # Check for circular extends chains
    for name in templates:
        visited = set()
        current = name
        while current and isinstance(templates.get(current), dict):
            if current in visited:
                errors.append(
                    f"{filename}: templates.{name}: circular extends chain detected"
                )
                break
            visited.add(current)
            current = templates[current].get("extends") if isinstance(templates.get(current), dict) else None


def validate_worker_pools(config, pool_group_names=None, filename="worker-pools.yml"):
    """Validate worker-pools.yml structure.

    Args:
        config: parsed YAML dict
        pool_group_names: set/list of valid pool-group names (from pool-groups.yml)
        filename: for error messages

    Returns a list of error/warning strings.
    """
    errors = []

    if not isinstance(config, dict):
        errors.append(f"{filename}: top-level must be a dict")
        return errors

    # Check unknown top-level keys
    for key in config:
        if key not in _WP_TOP_LEVEL_KNOWN:
            suggestion = _suggest(key, _WP_TOP_LEVEL_KNOWN)
            errors.append(f"{filename}: unknown top-level key '{key}'{suggestion}")

    if "pools" not in config:
        errors.append(f"{filename}: missing required key 'pools'")
        return errors

    pools = config["pools"]
    if not isinstance(pools, list):
        errors.append(f"{filename}: 'pools' must be a list")
        return errors

    templates = config.get("templates", {})
    machines = config.get("machines", {})

    # Validate templates
    if templates:
        _validate_template_extends(templates, filename, errors)

    # Validate each pool entry
    for i, entry in enumerate(pools):
        _validate_wp_pool_entry(entry, i, templates, machines, pool_group_names, filename, errors)

    return errors


# ---------------------------------------------------------------------------
# clients.yml
# ---------------------------------------------------------------------------

_CLIENTS_TOP_LEVEL_KNOWN = {
    "autophone-clients", "scriptworker-k8s-clients",
    "scriptworker-explicit-clients", "v3-mac-signing-clients",
    "generic-worker-clients", "single-scope-worker-clients", "clients",
}

_AUTOPHONE_GROUP_KNOWN = {"base-scopes", "worker-id-prefix", "devices"}
_AUTOPHONE_DEVICE_KNOWN = {"name", "queue", "description"}


def validate_clients(config, filename="clients.yml"):
    """Validate clients.yml structure.

    Returns a list of error/warning strings.
    """
    errors = []

    if not isinstance(config, dict):
        errors.append(f"{filename}: top-level must be a dict")
        return errors

    # Check unknown top-level keys (ignoring YAML anchor keys starting with _)
    for key in config:
        if key.startswith("_"):
            continue  # YAML anchors like _shipit_gecko_scopes
        if key not in _CLIENTS_TOP_LEVEL_KNOWN:
            suggestion = _suggest(key, _CLIENTS_TOP_LEVEL_KNOWN)
            errors.append(f"{filename}: unknown top-level key '{key}'{suggestion}")

    # Validate autophone-clients
    auto = config.get("autophone-clients", {})
    if isinstance(auto, dict):
        for group_name, group in auto.items():
            path = f"autophone-clients.{group_name}"
            if not isinstance(group, dict):
                errors.append(f"{filename}: {path}: must be a dict")
                continue

            _require_fields(group, ["base-scopes", "worker-id-prefix", "devices"], path, filename, errors)
            _check_unknown_fields(group, _AUTOPHONE_GROUP_KNOWN, path, filename, errors)

            if "base-scopes" in group and not isinstance(group["base-scopes"], list):
                errors.append(f"{filename}: {path}.base-scopes: must be a list")

            if "worker-id-prefix" in group and not isinstance(group["worker-id-prefix"], str):
                errors.append(f"{filename}: {path}.worker-id-prefix: must be a string")

            if "devices" in group:
                devices = group["devices"]
                if not isinstance(devices, list):
                    errors.append(f"{filename}: {path}.devices: must be a list")
                else:
                    for i, device in enumerate(devices):
                        dpath = f"{path}.devices[{i}]"
                        if not isinstance(device, dict):
                            errors.append(f"{filename}: {dpath}: must be a dict")
                            continue
                        if "name" not in device:
                            errors.append(f"{filename}: {dpath}: missing required field 'name'")
                        if "queue" not in device:
                            errors.append(f"{filename}: {dpath}: missing required field 'queue'")
                        _check_unknown_fields(device, _AUTOPHONE_DEVICE_KNOWN, dpath, filename, errors)

    # Validate scriptworker-k8s-clients
    sw = config.get("scriptworker-k8s-clients", {})
    if isinstance(sw, dict):
        for function, envs in sw.items():
            if not isinstance(envs, dict):
                errors.append(f"{filename}: scriptworker-k8s-clients.{function}: must be a dict with 'dev'/'prod' keys")
                continue
            for env_name in envs:
                if env_name not in ("dev", "prod"):
                    errors.append(
                        f"{filename}: scriptworker-k8s-clients.{function}: "
                        f"unknown environment '{env_name}' (expected 'dev' or 'prod')"
                    )

    # Validate single-scope-worker-clients
    ss = config.get("single-scope-worker-clients", {})
    if isinstance(ss, dict):
        for name, entry in ss.items():
            path = f"single-scope-worker-clients.{name}"
            if not isinstance(entry, dict):
                errors.append(f"{filename}: {path}: must be a dict")
                continue
            if "worker-type" not in entry:
                errors.append(f"{filename}: {path}: missing required field 'worker-type'")
            elif not isinstance(entry["worker-type"], str):
                errors.append(f"{filename}: {path}.worker-type: must be a string")

    return errors


# ---------------------------------------------------------------------------
# projects.yml
# ---------------------------------------------------------------------------

_PROJECTS_TOP_LEVEL_KNOWN = {"project-defaults", "projects"}

_PROJECT_KNOWN_FIELDS = {
    "defaults", "repo", "repo_type", "trust_domain", "trust_project",
    "access", "branches", "features", "features+", "default_branch",
    "is_try", "parent_repo", "lando_repo", "cron", "taskcluster_yml_project",
}

_PROJECT_DEFAULT_KNOWN_FIELDS = _PROJECT_KNOWN_FIELDS | {"extends"}


def _validate_extends_chains(defaults, section_name, filename, errors):
    """Check extends targets exist and there are no circular chains."""
    for name, defn in defaults.items():
        if not isinstance(defn, dict):
            continue
        if "extends" in defn:
            target = defn["extends"]
            if isinstance(target, str) and target not in defaults:
                suggestion = _suggest(target, list(defaults.keys()))
                errors.append(
                    f"{filename}: {section_name}.{name}.extends: "
                    f"references unknown default '{target}'{suggestion}"
                )

    # Check for circular chains
    for name in defaults:
        if not isinstance(defaults[name], dict):
            continue
        visited = set()
        current = name
        while current and isinstance(defaults.get(current), dict):
            if current in visited:
                errors.append(
                    f"{filename}: {section_name}.{name}: circular extends chain detected"
                )
                break
            visited.add(current)
            current = defaults[current].get("extends") if isinstance(defaults.get(current), dict) else None


def validate_projects(config, filename="projects.yml"):
    """Validate projects.yml structure.

    Returns a list of error/warning strings.
    """
    errors = []

    if not isinstance(config, dict):
        errors.append(f"{filename}: top-level must be a dict")
        return errors

    # Check unknown top-level keys
    for key in config:
        if key not in _PROJECTS_TOP_LEVEL_KNOWN:
            suggestion = _suggest(key, _PROJECTS_TOP_LEVEL_KNOWN)
            errors.append(f"{filename}: unknown top-level key '{key}'{suggestion}")

    # Validate project-defaults
    project_defaults = config.get("project-defaults", {})
    if isinstance(project_defaults, dict):
        _validate_extends_chains(project_defaults, "project-defaults", filename, errors)

        for name, defn in project_defaults.items():
            path = f"project-defaults.{name}"
            if not isinstance(defn, dict):
                errors.append(f"{filename}: {path}: must be a dict")
                continue
            for key in defn:
                if key not in _PROJECT_DEFAULT_KNOWN_FIELDS:
                    suggestion = _suggest(key, _PROJECT_DEFAULT_KNOWN_FIELDS)
                    errors.append(f"{filename}: {path}: unknown field '{key}'{suggestion}")

    # Validate projects
    projects = config.get("projects", {})
    if isinstance(projects, dict):
        for alias, project in projects.items():
            path = f"projects.{alias}"
            if not isinstance(project, dict):
                errors.append(f"{filename}: {path}: must be a dict")
                continue

            # Validate defaults reference
            if "defaults" in project:
                defaults_ref = project["defaults"]
                if isinstance(defaults_ref, str) and defaults_ref not in project_defaults:
                    suggestion = _suggest(defaults_ref, list(project_defaults.keys()))
                    errors.append(
                        f"{filename}: {path}.defaults: "
                        f"references unknown project-default '{defaults_ref}'{suggestion}"
                    )

            # Warn on unknown fields
            for key in project:
                if key not in _PROJECT_KNOWN_FIELDS:
                    suggestion = _suggest(key, _PROJECT_KNOWN_FIELDS)
                    errors.append(f"{filename}: {path}: unknown field '{key}'{suggestion}")

    return errors


# ---------------------------------------------------------------------------
# Top-level validation
# ---------------------------------------------------------------------------

def validate_schemas(base_dir="."):
    """Validate all config YAML files.

    Args:
        base_dir: directory containing the YAML files

    Returns:
        list of error/warning strings (empty means all valid)
    """
    import os
    errors = []

    # Load pool-groups first (needed for cross-references)
    pg_path = os.path.join(base_dir, "pool-groups.yml")
    pool_group_names = None
    if os.path.exists(pg_path):
        with open(pg_path) as f:
            pg_config = yaml.safe_load(f)
        pg_errors = validate_pool_groups(pg_config)
        errors.extend(pg_errors)

        # Build pool-group names for cross-reference validation
        if not pg_errors and isinstance(pg_config, dict) and "pool-groups" in pg_config:
            from expand.pool_groups import load_pool_groups
            pool_groups = load_pool_groups(pg_config)
            pool_group_names = set(pool_groups.keys())

    # Validate worker-pools.yml
    wp_path = os.path.join(base_dir, "worker-pools.yml")
    if os.path.exists(wp_path):
        with open(wp_path) as f:
            wp_config = yaml.safe_load(f)
        errors.extend(validate_worker_pools(wp_config, pool_group_names))

    # Validate clients.yml
    cl_path = os.path.join(base_dir, "clients.yml")
    if os.path.exists(cl_path):
        with open(cl_path) as f:
            cl_config = yaml.safe_load(f)
        errors.extend(validate_clients(cl_config))

    # Validate projects.yml
    pj_path = os.path.join(base_dir, "projects.yml")
    if os.path.exists(pj_path):
        with open(pj_path) as f:
            pj_config = yaml.safe_load(f)
        errors.extend(validate_projects(pj_config))

    return errors


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def main():
    """Run schema validation on all config files."""
    errors = validate_schemas()
    if errors:
        print(f"Schema validation found {len(errors)} issue(s):\n")
        for error in errors:
            print(f"  {error}")
        return 1
    else:
        print("All config files pass schema validation.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
