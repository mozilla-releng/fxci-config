# fxci-config Normalization — Ground-Up Refactor

**Date:** 2026-03-24
**Status:** Implemented (updated 2026-03-25 to reflect actual build)
**Goal:** Redesign all fxci-config YAML files to be the minimal data set that Python expands into the current 1,351 tc-admin resources.

## Problem

The current configuration (8,282 lines across 10 YAML files) is hard to understand and maintain. The organizational structure is implicit — pool-groups (`{trust_domain}-{level}`) tie entities together but are never declared. Variant lists repeat the same pool-group combinations and disk/machine configs hundreds of times. Adding a new pool-group or worker type requires touching many places.

## Approach

Make pool-groups a first-class concept. Design the smallest YAML representation where every value is stated once. Write a Python expansion layer (`expand/`) that transforms compressed config into the format `ciadmin` generators expect. Validate by comparing generated resources against a known-good baseline.

## Current State (Baseline)

| Entity | Count | Source File(s) |
|--------|-------|----------------|
| WorkerPool | 528 | worker-pools.yml (96 entries x variants) |
| Role | 565 | projects.yml x grants.d rules |
| Client | 249 | clients.yml + clients-interpreted.yml |
| Hook | 9 | hooks.yml |
| **Total** | **1,351** | **8,282 lines of YAML** |

Baseline captured at `/tmp/norm-v2-baseline.json` from upstream main.

## Architecture

```
Compressed YAML (pool-groups.yml, worker-pools.yml, clients.yml, projects.yml, hooks.yml)
        |
        v
    expand/  (NEW - fxci-config-specific)
        |  Reads compressed format, expands to full format
        v
    ciadmin/generate/*  (UNCHANGED)
        |
        v
    tc-admin resources (WorkerPool, Role, Client, Hook)
```

`expand/` sits between the config files and `ciadmin`. It reads the compressed YAML, expands all cross-products and rule-based derivations, and injects the results directly into ciadmin's config cache (`ciadmin.generate.ciconfig.get._cache`). `ciadmin` itself is not modified.

**Interface contract:** `expand/__init__.py:expand_all()` populates the cache keys that ciadmin's `fetch_all()` methods read. The expanded data replaces the originals as ciadmin's input.

**Worker pools cache schema:** The `worker-pools.yml` cache entry contains:
- `worker-defaults` — passed through verbatim from the `worker-defaults-passthrough` section of the compressed file. This section contains the full `by-implementation` worker-config blocks (docker-worker shutdown config, generic-worker Windows/Linux configs). It is not processed by expand.py — it is handed to ciadmin as-is for backward compatibility.
- `pool-templates` — empty dict `{}` (all template logic is resolved during expansion).
- `pools` — list of fully-expanded pool dicts matching the `WorkerPool` attrs class (`pool_id`, `description`, `owner`, `email_on_error`, `provider_id`, `config`, `attributes`, `variants`, `template: null`).

**Clients cache:** expand.py produces the expanded client dict and injects it at `clients.yml`. The `clients-interpreted.yml` cache key is set to an empty list `[]`, neutralising the `InterpretedClientConfig.fetch_all()` path — which previously expanded `{trust_domain}` template clients across the project list. All that expansion now happens inside `expand/clients.py`.

## Data Model

### 1. pool-groups.yml (NEW — 53 lines)

Declares the trust-domain x level matrix that currently exists only as an implicit naming convention. Matches the original spec design exactly.

```yaml
pool-groups:
  gecko:
    levels: [1, 2, 3]
    testing: true        # generates gecko-t
  comm:
    levels: [1, 2, 3]
    testing: true
  # ... ~19 trust domains total
```

**Expansion rules:**
- `gecko` with `levels: [1, 2, 3]` and `testing: true` produces pool-groups: `gecko-1`, `gecko-2`, `gecko-3`, `gecko-t`
- Level 3 automatically gets `chain-of-trust: trusted`
- `standalone` means the name is used as-is (no level suffix)

**Derived properties per pool-group:**
Each expanded pool-group carries:
- `trust_domain` — e.g. `gecko`
- `level` — e.g. `3`, `1`, or `t` (testing pseudo-level)
- `cot` — `True` for level 3, `False` otherwise

Note: `provider_id` and `image_prefix` are **not** derived properties of the pool-group. They are resolved at expansion time using `by-cot` expressions directly in each pool or template definition.

### 2. worker-pools.yml (REWRITTEN — 744 lines)

The file has five top-level sections:

**`defaults`** — global defaults (owner, email_on_error, regions, lifecycle).

**`worker-defaults-passthrough`** — verbatim `worker-defaults` block passed to ciadmin, containing `by-implementation` worker-config selections. Not processed by expand.py.

**`azure-shared`** — YAML anchors for reusable Azure config fragments (ARM template IDs, VM weights, location lists, suffix tables). Referenced via `*` in pool definitions.

**`templates`** — named templates providing shared pool config. Templates support `extends` for single-level and multi-level inheritance:

```yaml
templates:
  azure-base:
    cloud: azure
    implementation: generic-worker/windows
    spot: true

  azure-win11-x64-tester:
    extends: azure-base
    provider_id: azure2
    suffixes: *suffixes-win11-tester
    # ...
```

Template `extends` is resolved before any pool expansion — `_resolve_template_inheritance()` builds a fully-merged template dict that pools then reference.

**`machines`** — named machine presets using compact string notation:

```
machine-name: "machine_type boot:SIZE [lssd:N] [cpu:PLATFORM] [nested] [standard] [gpu:COUNTxTYPE]"
```

Examples:
```yaml
c3d-standard-16-lssd: "c3d-standard-16-lssd boot:60 lssd:1"
n1-highmem-8-75gb-v100x1: "n1-highmem-8 boot:75 cpu:Intel Skylake gpu:1xnvidia-tesla-v100"
n2-standard-8-75gb-lssd-nested: "n2-standard-8 boot:75 lssd:1 cpu:Intel Cascadelake nested"
```

The compact notation is parsed by `_expand_compact_machines()` into `{machine_type, disks, minCpuPlatform, guestAccelerators, ...}` dicts. Full dict form is also supported for machines that don't fit the compact notation.

**`pools`** — list of pool entries. Three structural forms exist beyond regular entries:

**Regular pool entry:**
```yaml
- pool_id: b-linux
  template: gcp-d2g-cot
  groups: [gecko, comm, app-services, enterprise]
  machine: c2-standard-16-2lssd-60gb
  maxCapacity: {by-trust-domain: {gecko: 1000, comm: 300, default: 100}}
```

**pool-table** — compact tabular format for pools sharing most properties, differing only in a few columns:
```yaml
- pool-table:
    description: Worker for Firefox automation.
    groups: [gecko-1]
    provider_id: fxci-level1-gcp
    machine: c2-standard-16-2lssd-20gb
    columns: [pool_id, image, maxCapacity, regions]
    rows:
      - [b-linux-gcp-relops1411, monopacker-docker-worker-2025-06-13-relops1411, 100, ~]
      - [b-linux-gcp-test-bug-1882320, monopacker-docker-worker-current, 5, [northamerica-northeast1]]
```

**pool-pair** — two pools (e.g. d2g and docker-worker variants) sharing common properties with per-variant overrides:
```yaml
- pool-pair:
    groups: [gecko, comm, mozillavpn]
    maxCapacity: {by-trust-domain: {gecko: 1000, comm: 20, default: 10}}
    variants:
      - {pool_id: b-linux-large, template: gcp-d2g-cot, machine: n2-standard-32-4lssd-60gb}
      - {pool_id: b-linux-large-gcp, template: gcp-docker-cot, machine: n2-standard-32-4lssd-20gb}
```

Both `pool-table` and `pool-pair` are pre-processed into regular pool entries before the main expansion loop.

**Key features:**

- **`groups` field** references pool-groups. A string matching a key in pool-groups.yml is treated as a trust-domain (expand all its non-testing levels); a string matching a specific pool-group name (e.g. `gecko-t`) is used as-is. A dict entry `{domain: {overrides}}` applies per-group field overrides.

- **`group-aliases`** — top-level section defining named lists of groups, referenced with `@alias-name` syntax in any `groups` list. Avoids repeating long group lists.

- **`suffixes`** — a pool with a `suffixes` dict produces one expanded pool per suffix value. The suffix is substituted into `{suffix}` placeholders in `pool_id`. Suffix entries can themselves contain `groups`, `implementation`, and other per-suffix overrides. Empty string suffix `''` produces the base pool name (trailing dashes are cleaned up).

- **`by-suffix` resolver** — resolves values keyed by suffix name (regex matching, same semantics as `by-pool-group`). Used heavily in Azure templates for per-suffix capacity, locations, and worker-config fields.

- **Value resolution** during expansion supports multiple axes. All resolve to concrete scalars before being handed to ciadmin:
  - `by-level` — resolves on trust level (1, 2, 3, or `t`)
  - `by-trust-domain` — resolves on trust domain name
  - `by-cot` — resolves on chain-of-trust status (`trusted` / `default`)
  - `by-suffix` — resolves on the current suffix value (regex matched)
  - These can be nested for multi-dimensional resolution
  - Replaces the current config's `by-pool-group` (53 occurrences) and `by-chain-of-trust` (13 occurrences)

- **Override mechanism:** The spec's explicit `overrides` dict per pool-group was not implemented. Instead, deviations are expressed through: per-group dict entries in `groups` lists, per-suffix properties in `suffixes`, and the `by-*` resolver system. The `pool-table` and `pool-pair` constructs handle the remaining structural variation.

- **`{chain-of-trust}` placeholder** in `implementation` strings is substituted at expansion time (e.g. `generic-worker/linux-d2g-{chain-of-trust}` → `generic-worker/linux-d2g-trusted` or `generic-worker/linux-d2g`).

- **String placeholders** `{pool-group}`, `{suffix}`, `{level}`, `{pool-id-base}` are substituted in string values within the expanded config.

**Azure and AWS pools:**
Azure pools are detected by `cloud: azure` in the template/entry and are built by `_build_azure_config()`. Azure-specific fields (ARM template IDs, VM weights, location lists) are defined as YAML anchors in the `azure-shared` section and referenced throughout pool definitions.

### 3. clients.yml (REWRITTEN — 873 lines)

Replaces both `clients.yml` and `clients-interpreted.yml`. The compressed format handles autophone, scriptworker-k8s, generic-worker, and one-off clients in a single file. `clients-interpreted.yml` absorption worked by setting the `clients-interpreted.yml` cache key to an empty list rather than writing an empty file — ciadmin's `InterpretedClientConfig.fetch_all()` returns nothing, and all previously-interpreted clients are now expanded by `expand/clients.py` directly.

The actual line count (873) is higher than the estimate (250) because the autophone and generic-worker sections enumerate individual devices and worker types explicitly rather than using a compact cross-product format.

### 4. projects.yml (REWRITTEN — 784 lines)

```yaml
project-defaults:
  gecko-hg:
    repo_type: hg
    features:
      gecko-actions: true
      # ...

  gecko-hg-full:
    extends: gecko-hg
    features+:
      scriptworker: true
      shipit: true

projects:
  mozilla-central:
    defaults: gecko-hg-full
    repo: https://hg.mozilla.org/mozilla-central
    trust_domain: gecko
    access: scm_level_3
```

**Merge semantics:**
- `defaults: name` — start with that default's fields
- `extends: name` — in project-defaults, inherit from another default
- `features+: {...}` — merge into features from defaults (additive)
- `features: {...}` (without `+`) — replace features entirely

### 5. hooks.yml (UNCHANGED — 319 lines)

Not rewritten in this iteration. The original file is used as-is.

## Expansion Logic (expand/)

The expansion layer is split into modules:

| Module | Lines | Purpose |
|--------|-------|---------|
| `expand/__init__.py` | 41 | `expand_all()` — loads files, calls sub-expanders, injects into ciadmin cache |
| `expand/pool_groups.py` | 36 | `load_pool_groups()` — parses pool-groups.yml, returns `{name: PoolGroup}` |
| `expand/resolve.py` | 38 | `resolve_value()` — resolves `by-level`, `by-trust-domain`, `by-cot` expressions |
| `expand/worker_pools.py` | 685 | `expand_worker_pools()` — full pool expansion including all constructs below |
| `expand/clients.py` | 214 | `expand_clients()` — expands all client sections |
| `expand/projects.py` | 215 | `expand_projects()` — merges project-defaults into projects |

### worker_pools.py key functions

```python
_resolve_template_inheritance(templates)  # resolves 'extends' chains before expansion
_expand_compact_machines(machines)         # parses compact string notation
_expand_pool_table(table)                  # pre-processes pool-table into regular entries
_expand_pool_pair(pair)                    # pre-processes pool-pair into regular entries
_expand_group_aliases(groups_list, aliases) # expands @alias-name references
_expand_groups_entry(groups_list, pool_groups) # resolves trust-domain names to pool-groups
_resolve_suffix(value, suffix, pool_group) # by-suffix resolver (regex matching)
_resolve_all(value, pool_group, suffix)    # calls resolve_value then _resolve_suffix
_expand_one_pool(...)                      # main per-pool-group expansion
_expand_standalone_pool(...)               # pools with no groups field
_build_config(...)                         # dispatches to GCP or Azure config builder
```

### Value Resolution

```yaml
# by-level
max_capacity: {by-level: {3: 500, t: 200, default: 1000}}

# by-trust-domain
max_capacity: {by-trust-domain: {gecko: 1000, comm: 300, default: 100}}

# by-cot (used for provider_id and image in templates)
provider_id: {by-cot: {trusted: fxci-level3-gcp, default: fxci-level1-gcp}}

# by-suffix (regex matched; used in Azure pools)
locations: {by-suffix: {ssd: *locs-ssd, default: *locs-11}}

# Nested multi-dimensional
max_capacity:
  by-trust-domain:
    gecko: {by-level: {3: 500, default: 1000}}
    comm: 300
    default: 100
```

`by-suffix` is resolved first (before `resolve_value`), then `by-level`, `by-trust-domain`, `by-cot` are resolved. Nesting across types is supported.

## Validation

Validation compares generated resources against the baseline. It is **not** a strict equality check.

### Process

1. Run `expand_all()` to populate ciadmin's config cache
2. Feed into `ciadmin` generators
3. Serialize all resources to JSON
4. Compare against baseline
5. Triage differences:
   - **Bug in original config** — inconsistency in current YAML that we fix (update baseline expectation)
   - **Innocuous difference** — ordering, whitespace, formatting (accept)
   - **Real regression** — expansion logic error (fix)

### validate.py (165 lines)

Compares expanded output against baseline. Prints categorized diffs. Returns exit code 0 if all diffs are triaged (accepted or fixed), non-zero if unresolved diffs remain.

**Triage persistence:** `accepted-diffs.json` records diffs that have been reviewed and accepted. `validate.py` skips these on subsequent runs.

## Actual Size Reduction

| File | Baseline Lines | Actual Lines | Reduction |
|------|---------------|--------------|-----------|
| worker-pools.yml | 4,009 | 744 | 81% |
| projects.yml | 1,545 | 784 | 49% |
| clients.yml | 1,350 | 873 | 35% |
| hooks.yml | 319 | 319 | 0% (not rewritten) |
| pool-groups.yml (new) | — | 53 | — |
| expand/ (new) | — | 1,229 | — |
| validate.py (new) | — | 165 | — |
| **Config total** | **8,282** | **2,773** | **67%** |
| **Config + code** | **8,282** | **4,167** | **50%** |

Notes: clients.yml reduction is lower than estimated because devices and worker types are enumerated individually. hooks.yml was deferred. The expansion layer (1,229 lines split across 5 modules) is larger than estimated (600-800 lines for a single file) but handles more constructs than originally designed.

## Design Decisions (Actual)

1. **Pool-groups are first-class.** The implicit `{trust_domain}-{level}` naming convention becomes an explicit declaration with defined expansion rules. Implemented as designed.

2. **Clean-slate compressed format.** No obligation to preserve existing concepts (keyed-by, YAML anchors in meta, pool-templates). Implemented as designed. YAML anchors are used within the compressed format for Azure shared config but are an authoring convenience, not a structural dependency.

3. **ciadmin unchanged.** The expansion layer injects into ciadmin's config cache rather than writing intermediate files. This avoids modifying shared infrastructure and eliminates file I/O in the expansion path.

4. **Override mechanism evolved.** The original spec's explicit `overrides` dict per pool-group was not built. Instead: `by-*` resolvers handle rule-based variation, per-group dict entries in `groups` lists handle group-specific overrides, and `pool-table`/`pool-pair` handle structural variation. The `by-suffix` resolver (not in original spec) handles suffix-specific variation in Azure pools.

5. **Additional constructs.** The following were added during implementation:
   - `pool-table` — compact tabular format for pools differing only in a few columns
   - `pool-pair` — two-variant pools (e.g. d2g + docker-worker) sharing most properties
   - `group-aliases` — named group lists referenced with `@alias-name`
   - `by-suffix` resolver — regex-matched resolution on the current suffix value
   - Compact machine notation — string format for GCP machine specs
   - Template `extends` — single/multi-level template inheritance

6. **provider_id and image_prefix resolved at expansion time.** These were originally spec'd as derived properties of each PoolGroup. In practice, they are expressed as `by-cot` expressions directly in templates and pool definitions, resolved during expansion. The PoolGroup carries only `trust_domain`, `level`, and `cot`.

7. **clients-interpreted.yml absorption.** The cache key is set to `[]` (empty list) rather than writing an empty file. All client expansion happens in `expand/clients.py`. The clients.yml line count is higher than estimated because devices are listed individually.

8. **Flexible validation.** Baseline comparison triages diffs rather than requiring exact match. Innocuous differences and bugs in the original config are expected. Implemented as designed.

## Scope

### In scope (completed)
- pool-groups.yml (new), worker-pools.yml, clients.yml (absorbs clients-interpreted.yml), projects.yml
- expand/ expansion layer (5 modules)
- validate.py baseline comparison tool

### Deferred
- **hooks.yml** — only 9 hooks; original file used unchanged
- **grants.d/** — The grants directory contains rules that generate 565 Roles by cross-producting projects x grant rules. This is complex, heavily regex-based, and generates correct output today.
- **Other config files** — actions.yml (118 lines), environments.yml (311 lines), worker-images.yml (243 lines), cron-task-template.yml (75 lines), hg-push-template.yml (78 lines). These are small and well-structured.
- **ciadmin source code** — No modifications to the shared ciadmin package.
