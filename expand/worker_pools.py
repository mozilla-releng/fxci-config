"""Expand worker-pools.yml into individual pool dicts.

Reads pool entries from worker-pools.yml and produces a flat list of
pool dicts in the format that ciadmin's WorkerPool attrs class expects.

The expansion pipeline is:
    1. Resolve template inheritance (extends chains)
    2. Expand compact machine notation into full dicts
    3. Expand pool-table / pool-pair shorthand into regular pool entries
    4. For each pool entry, resolve by-* expressions per pool-group
    5. Build cloud-specific config (GCP or Azure) from the resolved entry
"""

import copy
import re

import yaml

from expand.pool_groups import PoolGroup, load_pool_groups
from expand.resolve import resolve_value


# ---------------------------------------------------------------------------
# Field tables for table-driven config builders
# ---------------------------------------------------------------------------

# GCP: fields on the machine dict that map into a single instance_type entry.
_GCP_INSTANCE_TYPE_FIELDS = (
    "machine_type",
    "minCpuPlatform",
    "disks",
    "guestAccelerators",
    "advancedMachineFeatures",
    "scheduling",
)

# GCP: fields popped from the pool entry into the top-level config dict.
_GCP_ENTRY_FIELDS = (
    "maxCapacity",
    "minCapacity",
    "capacityPerInstance",
    "regions",
    "image",
    "worker-config",
)

# Azure: fields popped from the pool entry into config (truthy-guarded).
_AZURE_ENTRY_FIELDS = (
    "locations",
    "image",
    "image_resource_group",
    "vm_size",
    "armDeployment",
    "worker-config",
    "tags",
    "worker-manager-config",
)

# Azure: fields popped from the pool entry with ``is not None`` guard
# (so that explicit ``False`` / ``0`` values are preserved).
_AZURE_ENTRY_FIELDS_NOT_NONE = (
    "spot",
    "maxCapacity",
    "minCapacity",
)

# Azure: fields read from the machine dict (truthy-guarded).
_AZURE_MACHINE_FIELDS = (
    "ephemeral_disk",
    "caching",
)

# Azure: fields popped from the entry, falling back to the machine dict.
_AZURE_ENTRY_OR_MACHINE_FIELDS = (
    "managed_disk",
)

# Azure: fields popped from the entry only (truthy-guarded).
_AZURE_DISK_FIELDS = (
    "disk_controller_type",
    "nvme_placement",
)

# Fields that should never leak into the final config dict.
_NON_CONFIG_FIELDS = {
    "provider", "implementation", "worker-purpose",
    "cloud", "image_resource_group", "managed_disk",
    "worker-manager-config", "disk_controller_type",
    "nvme_placement", "extends",
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _deep_merge(base, override):
    """Recursively merge *override* into *base*, returning a new dict.

    Nested dicts are merged recursively; all other values are replaced.
    Both inputs are left unmodified (values are deep-copied).
    """
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


def _pop_fields(source, fields):
    """Pop *fields* from *source* dict, returning a dict of found values."""
    result = {}
    for field in fields:
        if field in source:
            result[field] = source.pop(field)
    return result


# ---------------------------------------------------------------------------
# by-* / suffix / placeholder resolution
# ---------------------------------------------------------------------------

def _resolve_suffix(value, suffix, pool_group):
    """Resolve ``by-suffix`` expressions in *value*.

    Works like ``by-pool-group``: each key is tested as a regex against
    *suffix*, and the first match wins.  Falls back to ``default`` if present.
    """
    if not isinstance(value, dict):
        return value

    keys = list(value.keys())
    if len(keys) == 1 and keys[0] == "by-suffix":
        alternatives = value["by-suffix"]
        for alt_key, alt_value in alternatives.items():
            if alt_key == "default":
                continue
            if re.fullmatch(alt_key, suffix):
                return _resolve_suffix(alt_value, suffix, pool_group)
        if "default" in alternatives:
            return _resolve_suffix(alternatives["default"], suffix, pool_group)
        raise KeyError(
            f"No match for by-suffix={suffix!r} in {list(alternatives.keys())} "
            f"and no default (pool-group: {pool_group.name})"
        )

    # Recurse into dict values
    return {k: _resolve_suffix(v, suffix, pool_group) for k, v in value.items()}


def _resolve_all(value, pool_group, suffix=None):
    """Resolve all ``by-*`` expressions in a value tree.

    If *suffix* is given, ``by-suffix`` is resolved first, then the
    remaining ``by-pool-group`` / ``by-level`` expressions via
    :func:`resolve_value`.
    """
    if suffix is not None:
        value = _resolve_suffix(value, suffix, pool_group)
    return resolve_value(value, pool_group)


def _substitute_placeholders(value, pool_group, suffix="", pool_id_base=""):
    """Replace ``{pool-group}``, ``{suffix}``, ``{level}``, ``{pool-id-base}`` in strings.

    Recurses into dicts and lists so that the entire config tree is covered.
    """
    if isinstance(value, str):
        result = value
        result = result.replace("{pool-group}", pool_group.name)
        result = result.replace("{suffix}", suffix)
        result = result.replace("{level}", str(pool_group.level))
        if pool_id_base:
            result = result.replace("{pool-id-base}", pool_id_base)
        return result
    elif isinstance(value, dict):
        return {k: _substitute_placeholders(v, pool_group, suffix, pool_id_base) for k, v in value.items()}
    elif isinstance(value, list):
        return [_substitute_placeholders(v, pool_group, suffix, pool_id_base) for v in value]
    return value


def _resolve_implementation_cot(impl_str, pool_group):
    """Resolve ``{chain-of-trust}`` placeholder in implementation strings."""
    if "{chain-of-trust}" in impl_str:
        cot_val = "trusted" if pool_group.cot else ""
        impl_str = impl_str.replace("{chain-of-trust}", cot_val)
        # Clean up trailing dash if cot is empty
        impl_str = impl_str.rstrip("-")
    return impl_str


# ---------------------------------------------------------------------------
# Group / alias helpers
# ---------------------------------------------------------------------------

def _expand_group_aliases(groups_list, group_aliases):
    """Expand ``@alias`` references in a groups list.

    If a group name starts with ``@``, it is looked up in *group_aliases*
    and replaced with the referenced list of groups.
    """
    if not group_aliases:
        return groups_list
    result = []
    for entry in groups_list:
        if isinstance(entry, str) and entry.startswith("@"):
            alias_name = entry[1:]
            if alias_name in group_aliases:
                result.extend(group_aliases[alias_name])
            else:
                raise KeyError(f"Unknown group alias: {entry}")
        else:
            result.append(entry)
    return result


def _expand_groups_entry(groups_list, pool_groups):
    """Expand a groups list to concrete pool-group names.

    Each entry can be:
    - A specific pool-group name (e.g. ``gecko-1``) -- used as-is.
    - A trust-domain name (e.g. ``gecko``) -- expanded to all its levels,
      excluding the testing level (``-t``).  Use ``gecko-t`` explicitly to
      include it.
    - A dict ``{trust-domain: {overrides}}`` -- expanded to all levels for
      that trust-domain (including ``-t``).
    """
    result = []
    for entry in groups_list:
        if isinstance(entry, str):
            if entry in pool_groups:
                result.append(entry)
            else:
                for pg_name, pg in pool_groups.items():
                    if pg.trust_domain == entry and pg.level != "t":
                        result.append(pg_name)
        elif isinstance(entry, dict):
            for domain, overrides in entry.items():
                for pg_name, pg in pool_groups.items():
                    if pg.trust_domain == domain:
                        result.append(pg_name)
    return result


# ---------------------------------------------------------------------------
# Template inheritance
# ---------------------------------------------------------------------------

def _resolve_template_inheritance(templates):
    """Resolve ``extends`` chains in templates, returning fully-merged copies.

    Supports multi-level inheritance.  Cycles are not detected (assumed
    absent in well-formed input).
    """
    resolved = {}

    def resolve_one(name):
        if name in resolved:
            return resolved[name]
        tmpl = copy.deepcopy(templates[name])
        if "extends" in tmpl:
            parent_name = tmpl.pop("extends")
            parent = resolve_one(parent_name)
            tmpl = _deep_merge(copy.deepcopy(parent), tmpl)
        resolved[name] = tmpl
        return tmpl

    for name in templates:
        resolve_one(name)
    return resolved


# ---------------------------------------------------------------------------
# Pool-table / pool-pair expansion
# ---------------------------------------------------------------------------

def _expand_pool_table(table):
    """Expand a ``pool-table`` entry into a list of regular pool entries.

    A pool-table is a compact tabular format for pools that share most
    properties and differ only in a few fields (columns)::

        pool-table:
          template: translations-d2g
          groups: [translations-1]
          columns: [pool_id, machine, maxCapacity, description]
          rows:
            - [b-linux-large-gcp-d2g, n2-highmem-32-60gb, 1000, "Workers..."]
            - {pool_id: ..., machine: ..., extra_field: ...}

    Shared properties (everything except ``columns`` and ``rows``) are merged
    into each row entry, with row values taking precedence.
    """
    columns = table.pop("columns")
    rows = table.pop("rows")
    shared = table  # everything else is shared

    result = []
    for row in rows:
        entry = copy.deepcopy(shared)
        if isinstance(row, list):
            for i, col in enumerate(columns):
                if i < len(row) and row[i] is not None:
                    entry[col] = row[i]
        elif isinstance(row, dict):
            entry.update(row)
        result.append(entry)
    return result


def _expand_pool_pair(pair):
    """Expand a ``pool-pair`` entry into two regular pool entries.

    A pool-pair defines two pools (typically d2g and docker-worker) that
    share most properties but differ in a few fields::

        pool-pair:
          pool_id: b-linux-xlarge
          groups: [gecko, comm]
          maxCapacity: ...
          variants:
            - {pool_id: ..., template: gcp-d2g-cot, machine: ...}
            - {pool_id: ..., template: gcp-docker-cot, machine: ...}

    Each variant is deep-merged on top of the shared properties.
    """
    variants = pair.pop("variants")
    shared = pair

    result = []
    for variant in variants:
        entry = copy.deepcopy(shared)
        for k, v in variant.items():
            if isinstance(v, dict) and k in entry and isinstance(entry[k], dict):
                entry[k] = _deep_merge(entry[k], v)
            else:
                entry[k] = copy.deepcopy(v)
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Compact machine notation parser
# ---------------------------------------------------------------------------

def _expand_compact_machines(machines):
    """Expand compact machine string notation into full machine dicts.

    Grammar (whitespace-separated tokens after the machine type)::

        MACHINE  := machine_type TOKEN*
        TOKEN    := boot:SIZE          -- boot disk, SIZE in GB
                  | lssd:N             -- N local-SSD disks
                  | cpu:PLATFORM       -- min CPU platform (may contain spaces,
                  |                       consumes tokens until next keyword)
                  | nested             -- enable nested virtualisation
                  | standard           -- use "standard" scheduling
                  | gpu:COUNTxTYPE     -- guest accelerator

    Examples::

        "n2-standard-8 boot:50"
        "c2-standard-4 boot:75 lssd:1 cpu:Intel Cascadelake"
        "n1-standard-8 boot:50 gpu:4xnvidia-tesla-v100"

    If the value is already a dict it is passed through unchanged.
    """
    # Keywords that signal the start of a new token (used to delimit
    # the multi-word ``cpu:`` platform name).
    _KEYWORDS = ("boot:", "lssd:", "cpu:", "gpu:", "nested", "standard")

    result = {}
    for name, value in machines.items():
        if not isinstance(value, str):
            result[name] = value
            continue

        parts = value.split()
        machine = {"machine_type": parts[0]}
        disks = []
        i = 1
        while i < len(parts):
            part = parts[i]
            if part.startswith("boot:"):
                disks.append({"type": "boot", "size_gb": int(part[5:])})
            elif part.startswith("lssd:"):
                disks.extend([{"type": "local-ssd"}] * int(part[5:]))
            elif part.startswith("cpu:"):
                # CPU platform names can contain spaces (e.g. "Intel Cascadelake"),
                # so consume tokens until the next keyword or end of string.
                cpu_parts = [part[4:]]
                i += 1
                while i < len(parts) and not any(parts[i].startswith(p) for p in _KEYWORDS):
                    cpu_parts.append(parts[i])
                    i += 1
                machine["minCpuPlatform"] = " ".join(cpu_parts)
                continue  # skip the i += 1 below
            elif part == "nested":
                machine.setdefault("advancedMachineFeatures", {})["enableNestedVirtualization"] = True
            elif part == "standard":
                machine["scheduling"] = "standard"
            elif part.startswith("gpu:"):
                # Format: gpu:COUNTxTYPE  e.g. gpu:4xnvidia-tesla-v100
                count_str, gpu_type = part[4:].split("x", 1)
                machine.setdefault("guestAccelerators", []).append({
                    "acceleratorCount": int(count_str),
                    "acceleratorType": gpu_type,
                })
            i += 1

        if disks:
            machine["disks"] = disks
        result[name] = machine
    return result


# ---------------------------------------------------------------------------
# Cloud-specific config builders (table-driven)
# ---------------------------------------------------------------------------

def _resolve_machine(machine_name, machine_override, machines):
    """Look up *machine_name* in presets, apply *machine_override*, return dict.

    Returns an empty dict when no machine information is available.
    """
    if machine_name and machine_name in machines:
        machine = copy.deepcopy(machines[machine_name])
    elif machine_name:
        # Not found in presets -- treat as an inline machine type.
        machine = {"machine_type": machine_name}
    else:
        machine = {}

    if machine_override:
        machine = _deep_merge(machine, machine_override) if machine else copy.deepcopy(machine_override)
    return machine


def _build_gcp_config(entry, machine, implementation, defaults):
    """Build GCP provider config from *entry* and resolved *machine* dict.

    GCP pools use an ``instance_types`` list (with a single entry) to
    describe the VM shape, plus top-level capacity / region / image fields.
    """
    config = {}

    # -- instance_types from machine preset (table-driven) --
    if machine:
        instance_type = {k: machine[k] for k in _GCP_INSTANCE_TYPE_FIELDS if k in machine}
        if instance_type:
            config["instance_types"] = [instance_type]

    # -- fields extracted from the pool entry --
    config.update(_pop_fields(entry, _GCP_ENTRY_FIELDS))

    # -- implementation --
    if implementation:
        config["implementation"] = implementation

    # -- lifecycle from defaults --
    if "lifecycle" in defaults:
        config["lifecycle"] = copy.deepcopy(defaults["lifecycle"])

    return config


def _build_azure_config(entry, machine, implementation, worker_purpose):
    """Build Azure provider config from *entry* and resolved *machine* dict.

    Azure pools describe the VM via a flat ``vm_size`` string.  Disk
    properties (ephemeral, caching, managed, controller type) come from
    both the machine preset and the pool entry.
    """
    config = {}

    # -- vm_size: entry wins, then machine fallback --
    vm_size = entry.pop("vm_size", None)
    if vm_size is None and "vm_size" in machine:
        vm_size = machine["vm_size"]

    # -- capacity (not-None guard so 0 is preserved) --
    for field in _AZURE_ENTRY_FIELDS_NOT_NONE:
        val = entry.pop(field, None)
        if val is not None:
            config[field] = val

    # -- fields from the pool entry (truthy guard) --
    for field in _AZURE_ENTRY_FIELDS:
        val = entry.pop(field, None)
        if val:
            config[field] = val

    # -- vm_size (after entry fields, so it overwrites if both present) --
    if vm_size:
        config["vm_size"] = vm_size

    # -- implementation / worker-purpose --
    if implementation:
        config["implementation"] = implementation
    if worker_purpose:
        config["worker-purpose"] = worker_purpose

    # -- disk settings from machine preset --
    for field in _AZURE_MACHINE_FIELDS:
        val = machine.get(field)
        if val:
            config[field] = True if field == "ephemeral_disk" else val

    # -- disk settings from entry, with machine fallback --
    for field in _AZURE_ENTRY_OR_MACHINE_FIELDS:
        val = entry.pop(field, machine.get(field))
        if val:
            config[field] = val

    # -- disk settings from entry only --
    for field in _AZURE_DISK_FIELDS:
        val = entry.pop(field, None)
        if val:
            config[field] = val

    return config


# ---------------------------------------------------------------------------
# Config routing
# ---------------------------------------------------------------------------

def _build_config(entry, machine_name, machine_override, machines, defaults, pg=None, suffix=None):
    """Build the cloud-specific config dict for a single pool.

    Determines the cloud provider from the ``cloud`` field (defaulting to
    GCP) and delegates to :func:`_build_gcp_config` or
    :func:`_build_azure_config`.
    """
    machine = _resolve_machine(machine_name, machine_override, machines)

    cloud = entry.pop("cloud", None)
    implementation = entry.pop("implementation", None)
    worker_purpose = entry.pop("worker-purpose", None)

    if cloud == "azure":
        config = _build_azure_config(entry, machine, implementation, worker_purpose)
    else:
        config = _build_gcp_config(entry, machine, implementation, defaults)

    # Remove non-config fields that may have leaked in from templates.
    for field in _NON_CONFIG_FIELDS:
        config.pop(field, None)
        entry.pop(field, None)

    return config


# ---------------------------------------------------------------------------
# Pool-level expansion
# ---------------------------------------------------------------------------

def _make_pool_dict(pool_id, description, owner, email_on_error, provider_id, config):
    """Return the canonical pool dict structure expected by ciadmin."""
    return {
        "pool_id": pool_id,
        "description": description,
        "owner": owner,
        "email_on_error": email_on_error,
        "provider_id": provider_id,
        "config": config,
        "attributes": {},
        "variants": [{}],
        "template": None,
    }


def _extract_pool_metadata(entry, defaults):
    """Pop owner / description / email_on_error / provider_id from *entry*.

    Falls back to *defaults* for owner and email_on_error.
    """
    return (
        entry.pop("owner", defaults.get("owner")),
        entry.pop("description", ""),
        entry.pop("email_on_error", defaults.get("email_on_error", True)),
        entry.pop("provider_id", None),
    )


def _expand_standalone_pool(pool_id, entry, defaults, templates, template_name, machines, result):
    """Expand a pool that has no groups (standalone, fully-qualified pool_id)."""
    entry = copy.deepcopy(entry)

    if template_name:
        template = copy.deepcopy(templates[template_name])
        entry = _deep_merge(template, entry)

    machine_name = entry.pop("machine", None)
    machine_override = entry.pop("machine-override", None)
    owner, description, email_on_error, provider_id = _extract_pool_metadata(entry, defaults)

    config = _build_config(entry, machine_name, machine_override, machines, defaults)

    result.append(_make_pool_dict(pool_id, description, owner, email_on_error, provider_id, config))


def _expand_one_pool(pool_id, entry, groups_list, pool_groups, defaults,
                     templates, template_name, machines, suffix, result):
    """Expand a pool entry once for each pool-group in *groups_list*."""
    expanded_groups = _expand_groups_entry(groups_list, pool_groups)

    for pg_name in expanded_groups:
        if pg_name not in pool_groups:
            continue
        pg = pool_groups[pg_name]

        work = copy.deepcopy(entry)

        if template_name:
            template = copy.deepcopy(templates[template_name])
            work = _deep_merge(template, work)

        # Resolve all by-* expressions (but not machine-override, which is structural).
        resolved = {}
        for k, v in work.items():
            if k in ("machine-override",):
                resolved[k] = v
            else:
                resolved[k] = _resolve_all(v, pg, suffix=suffix)

        owner, description, email_on_error, provider_id = _extract_pool_metadata(resolved, defaults)

        # Build the pool_id
        actual_pool_id = pool_id if "/" in pool_id else f"{pg_name}/{pool_id}"
        actual_pool_id = _substitute_placeholders(actual_pool_id, pg, suffix or "")
        pool_id_base = actual_pool_id.split("/", 1)[1] if "/" in actual_pool_id else actual_pool_id

        # Build config
        machine_name = resolved.pop("machine", None)
        machine_override = resolved.pop("machine-override", None)
        config = _build_config(resolved, machine_name, machine_override, machines, defaults, pg, suffix)

        # Substitute placeholders throughout config and description.
        config = _substitute_placeholders(config, pg, suffix or "", pool_id_base)
        description = _substitute_placeholders(description, pg, suffix or "", pool_id_base)

        result.append(_make_pool_dict(actual_pool_id, description, owner, email_on_error, provider_id, config))


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def expand_worker_pools(config, pool_groups):
    """Expand compressed worker-pools config into a list of pool dicts.

    This is the main entry point.  It processes the parsed YAML from
    ``worker-pools.yml`` through template resolution, machine expansion,
    pool-table/pair expansion, suffix expansion, and per-pool-group
    instantiation.

    Args:
        config: parsed worker-pools.yml (dict).
        pool_groups: dict of pool-group name to
            :class:`~expand.pool_groups.PoolGroup`.

    Returns:
        list of expanded pool dicts ready for ciadmin.
    """
    defaults = config.get("defaults", {})
    templates = _resolve_template_inheritance(config.get("templates", {}))
    machines = _expand_compact_machines(config.get("machines", {}))
    group_aliases = config.get("group-aliases", {})
    pools = config.get("pools", [])

    # Pre-process: expand pool-table and pool-pair entries into regular pool entries.
    expanded_pools = []
    for pool_entry in pools:
        if "pool-table" in pool_entry:
            expanded_pools.extend(_expand_pool_table(pool_entry["pool-table"]))
        elif "pool-pair" in pool_entry:
            expanded_pools.extend(_expand_pool_pair(pool_entry["pool-pair"]))
        else:
            expanded_pools.append(pool_entry)
    pools = expanded_pools

    result = []

    for pool_entry in pools:
        pool_entry = copy.deepcopy(pool_entry)

        # Apply template early so suffixes/groups from templates are available.
        template_name = pool_entry.pop("template", None)
        if template_name:
            template = copy.deepcopy(templates[template_name])
            pool_entry = _deep_merge(template, pool_entry)

        suffixes = pool_entry.pop("suffixes", None)
        groups_from_pool = pool_entry.pop("groups", None)
        pool_id_pattern = pool_entry.pop("pool_id")

        if groups_from_pool is not None:
            groups_from_pool = _expand_group_aliases(groups_from_pool, group_aliases)

        if suffixes is not None:
            # Suffix expansion: each suffix produces a separate pool variant.
            for suffix_val, suffix_props in suffixes.items():
                suffix_props = copy.deepcopy(suffix_props) if suffix_props else {}
                suffix_groups = suffix_props.pop("groups", groups_from_pool)

                if suffix_groups is not None:
                    suffix_groups = _expand_group_aliases(suffix_groups, group_aliases)
                if suffix_groups is None:
                    continue

                # Build pool_id with suffix substituted, collapsing double dashes.
                actual_pool_id = pool_id_pattern.replace("{suffix}", suffix_val)
                while "--" in actual_pool_id:
                    actual_pool_id = actual_pool_id.replace("--", "-")
                actual_pool_id = actual_pool_id.rstrip("-")

                suffix_entry = copy.deepcopy(pool_entry)
                for k, v in suffix_props.items():
                    suffix_entry[k] = v

                _expand_one_pool(
                    pool_id=actual_pool_id,
                    entry=suffix_entry,
                    groups_list=suffix_groups,
                    pool_groups=pool_groups,
                    defaults=defaults,
                    templates=templates,
                    template_name=None,
                    machines=machines,
                    suffix=suffix_val,
                    result=result,
                )
        elif groups_from_pool is None:
            # Standalone pool (e.g. infra/build-decision) with a fully-qualified pool_id.
            _expand_standalone_pool(
                pool_id=pool_id_pattern,
                entry=pool_entry,
                defaults=defaults,
                templates=templates,
                template_name=None,
                machines=machines,
                result=result,
            )
        else:
            _expand_one_pool(
                pool_id=pool_id_pattern,
                entry=pool_entry,
                groups_list=groups_from_pool,
                pool_groups=pool_groups,
                defaults=defaults,
                templates=templates,
                template_name=None,
                machines=machines,
                suffix=None,
                result=result,
            )

    return result


def expand_worker_pools_from_files(compressed_path="worker-pools.yml",
                                    pool_groups_path="pool-groups.yml"):
    """Convenience wrapper: load YAML files and expand."""
    with open(compressed_path) as f:
        config = yaml.safe_load(f)
    with open(pool_groups_path) as f:
        pg_config = yaml.safe_load(f)
    pool_groups = load_pool_groups(pg_config)
    return expand_worker_pools(config, pool_groups)
