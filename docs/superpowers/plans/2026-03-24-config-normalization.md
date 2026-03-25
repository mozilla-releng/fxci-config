# Config Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fxci-config's 8,282 lines of YAML with ~1,710 lines of compressed config plus a Python expansion layer that produces identical tc-admin resources.

**Architecture:** A new `expand.py` module reads normalized YAML files (pool-groups.yml, worker-pools.yml, clients.yml, projects.yml) and injects the expanded data into ciadmin's config cache (`get._cache`) before generators run. ciadmin reads from cache, not disk. A `validate.py` script compares generated resources against a known-good baseline.

**Tech Stack:** Python 3.11+, PyYAML, attrs, pytest, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-03-24-config-normalization-design.md`

---

## Important: Disposable Code Policy

**The `src/ciadmin/` package is local to this repo** — it is NOT an external dependency. It can be freely modified, simplified, or replaced. The only external dependency is `tc-admin` (the `tcadmin` package), which provides the framework (AppConfig, Resources, resource types like WorkerPool/Client/Role).

**Old code is reference material, not sacred.** When implementing the expansion layer:
- The original YAML files (worker-pools.yml, clients.yml, etc.) are data to mine for patterns. Do NOT try to modify them incrementally — create the compressed versions from scratch.
- The old generators in `src/ciadmin/generate/` (worker_pools.py's 920 lines of template/variant/keyed-by logic, clients.py, etc.) are reference for understanding what output is expected. Once expand.py produces fully-resolved data, these generators can be simplified to just "take expanded dict, emit tc-admin resource."
- The old tests in `tests/ciadmin/` test the old loading/generation paths. They can be replaced by the new `tests/expand/` tests. Don't waste time making old tests pass against new code.
- The old ciconfig loaders (`src/ciadmin/generate/ciconfig/worker_pools.py`, `clients.py`, etc.) become trivial once expand.py populates the cache — they just read from cache.

**What MUST be preserved:**
- The `tcadmin` framework interface — `boot()`, `update_resources(resources)`, `resources.manage()`, `resources.add()`
- The tc-admin resource types — `WorkerPool`, `Client`, `Role`, `Hook` from `tcadmin.resources`
- The cloud provider config builders in `worker_pools.py` (`get_gcp_provider_config`, `get_azure_provider_config`, `get_aws_provider_config`) — these translate pool config into the exact JSON that Taskcluster worker-manager expects. They are complex and correct; reuse them.
- The grants system (`grants.d/`, `generate/grants.py`, `generate/scm_group_roles.py`) — out of scope, must keep working

---

## File Structure

### New files (in repo root)
- `pool-groups.yml` — trust-domain x level matrix (~60 lines)
- `expand.py` — expansion layer entry point, orchestrates all expanders (~100 lines)
- `expand/` — expansion modules directory
  - `__init__.py`
  - `pool_groups.py` — load and expand pool-group definitions (~80 lines)
  - `worker_pools.py` — expand compressed pool definitions (~300 lines)
  - `clients.py` — expand client templates (~150 lines)
  - `projects.py` — merge project defaults (~80 lines)
  - `resolve.py` — by-level, by-trust-domain, by-cot value resolver (~100 lines)
- `validate.py` — baseline comparison tool (~150 lines)
- `accepted-diffs.json` — triaged diff persistence (starts empty `[]`)
- `tests/expand/` — tests for the expansion layer
  - `conftest.py` — shared fixtures
  - `test_pool_groups.py`
  - `test_resolve.py`
  - `test_worker_pools.py`
  - `test_clients.py`
  - `test_projects.py`
  - `test_validate.py`

### Modified files
- `tc-admin.py` — call expand.py to populate ciadmin cache before boot()
- `src/ciadmin/generate/worker_pools.py` — simplified (template/variant/keyed-by logic removed; cloud provider config builders preserved)
- `src/ciadmin/generate/clients.py` — simplified (interpreted client logic removed)

### Removed at cutover
- `worker-pools.yml` — replaced by `worker-pools.yml` + expansion
- `clients.yml` — replaced by `clients.yml` + expansion
- `clients-interpreted.yml` — absorbed into `clients.yml`
- `projects.yml` — replaced by `projects.yml` + expansion
- Old tests in `tests/ciadmin/` that test replaced loading paths

### Unchanged files
- `src/ciadmin/boot.py` — entry point, registers generators
- `src/ciadmin/generate/grants.py` — grant system (out of scope)
- `src/ciadmin/generate/scm_group_roles.py` — out of scope
- `src/ciadmin/generate/ciconfig/get.py` — config loader with cache (expand.py injects here)
- `grants.d/` — grant rules untouched
- `hooks.yml` — deferred to future iteration
- `environments.yml`, `actions.yml`, `worker-images.yml` — untouched

---

## Phase 0: Capture Baseline, Clean House, Plan CI

### Task 0: Generate baseline, archive old code, simplify generators

Before any agent works on the new system, we must:
1. Capture the exact output the old code produces (the target we're building toward)
2. Archive old config YAML so agents can mine it for patterns
3. Remove old tests that test replaced functionality
4. Simplify (not delete) the generators — strip template/variant/keyed-by complexity, keep cloud provider config builders and the `update_resources()` entry points that boot.py and the check files depend on

**Why simplify instead of delete generators:** The `src/ciadmin/check/` validation tests (run in CI via `tc-admin check`) import from `src/ciadmin/generate/worker_pools.py` — specifically `generate_pool_variants()` and `make_worker_pool()`. The `boot.py` entry point registers `worker_pools.update_resources`. Rather than breaking all these imports, we simplify the generator: `generate_pool_variants()` becomes trivial (pools are already expanded in cache), while the cloud provider builders (`get_gcp_provider_config`, `get_azure_provider_config`, `get_aws_provider_config`) and `make_worker_pool()` stay intact.

#### CI Impact Analysis

**Current CI pipeline:**
1. `uv run pytest tests -vv` — unit tests for ciadmin
2. `tc-admin check --environment staging/firefoxci` — generates resources and runs check_*.py validations
3. `tc-admin apply --environment staging` — deploys to staging
4. Integration tests against staging Taskcluster
5. GitHub Actions (`.github/workflows/deploy.yml`): runs `tc-admin check` on PRs, `tc-admin apply` on merge to main

**What breaks and how we fix it:**

| CI Step | Impact | Fix |
|---------|--------|-----|
| `pytest tests -vv` | Old worker pool/client tests deleted | New `tests/expand/` tests replace them |
| `tc-admin check` | check_worker_pools.py imports from generator | Generator simplified but entry points preserved; expand.py populates cache first |
| `tc-admin apply` | Needs all resources generated | expand.py runs before boot(); all generators still registered |
| Integration tests | No direct impact | They test against staging which receives generated resources |
| GitHub Actions | Calls tc-admin check/apply | Works once expand.py is wired into tc-admin.py |

**Test migration plan:**

| Old Test | Action | Replacement |
|----------|--------|-------------|
| `test_generate_ciconfig_worker_pools.py` | DELETE | `tests/expand/test_worker_pools.py` |
| `test_generate_worker_pools.py` | DELETE | `tests/expand/test_worker_pools.py` + `test_integration.py` |
| `test_generate_ciconfig_get.py` | KEEP | Still tests the cache/loading infrastructure |
| `test_generate_ciconfig_grants.py` | KEEP | Grants system unchanged |
| `test_generate_ciconfig_projects.py` | KEEP initially, REPLACE later | Projects loader used by grants; replace when projects.yml is done |
| `test_generate_ciconfig_actions.py` | KEEP | Actions unchanged |
| `test_generate_ciconfig_worker_images.py` | KEEP | Worker images unchanged |
| `test_generate_grants.py` | KEEP | Grants system unchanged |
| `test_generate_tcyml.py` | KEEP | TCYml unchanged |
| `test_util_matching.py` | KEEP | Matching utils unchanged |
| `test_util_templates.py` | KEEP | Template utils unchanged |
| `conftest.py` | KEEP | Fixtures used by kept tests |
| All `taskcluster/test/` tests | KEEP | TaskGraph transforms unchanged |
| All `src/ciadmin/check/` checks | KEEP | Work via cache injection |

**Files:**
- Create: `baseline/resources.json` — the target output (DO NOT MODIFY after creation)
- Create: `baseline/README` — explains what this is and that it must not be edited
- Archive: `worker-pools.yml`, `clients.yml`, `clients-interpreted.yml`, `projects.yml` → `baseline/old-config/`
- Delete: `tests/ciadmin/test_generate_worker_pools.py`, `tests/ciadmin/test_generate_ciconfig_worker_pools.py`
- Simplify: `src/ciadmin/generate/worker_pools.py` — strip template/variant/keyed-by code (~920 → ~400 lines), keep cloud builders + entry points
- Simplify: `src/ciadmin/generate/clients.py` — strip interpreted client logic, keep `update_resources()`
- Simplify: `src/ciadmin/generate/ciconfig/clients_interpreted.py` — empty `fetch_all()` returning `[]`
- Keep: Everything else (boot.py, checks, grants, hooks, ciconfig loaders, utils)

- [ ] **Step 1: Generate the baseline**

The baseline already exists at `/tmp/norm-v2-baseline.json` (295,781 lines, captured from upstream main). Copy it into the repo.

```bash
cd /Users/pmoore/git/fxci-config
mkdir -p baseline
cp /tmp/norm-v2-baseline.json baseline/resources.json
```

- [ ] **Step 2: Create baseline README**

```
baseline/README

THIS DIRECTORY CONTAINS THE TARGET OUTPUT FOR THE CONFIG NORMALIZATION.

baseline/resources.json is the exact set of tc-admin resources that the OLD
code produced. The new expansion layer must produce identical resources
(modulo accepted innocuous differences tracked in accepted-diffs.json).

DO NOT MODIFY these files. They are the ground truth we validate against.
Generated from upstream main before the refactor began.
```

- [ ] **Step 3: Archive old config files for reference**

Move the original YAML files to an archive directory. Agents should read these to understand patterns but never modify them.

```bash
cd /Users/pmoore/git/fxci-config
mkdir -p baseline/old-config
mv worker-pools.yml baseline/old-config/
mv clients.yml baseline/old-config/
mv clients-interpreted.yml baseline/old-config/
mv projects.yml baseline/old-config/
```

- [ ] **Step 4: Delete old tests for replaced functionality**

```bash
cd /Users/pmoore/git/fxci-config
rm tests/ciadmin/test_generate_worker_pools.py
rm tests/ciadmin/test_generate_ciconfig_worker_pools.py
```

- [ ] **Step 5: Simplify worker_pools.py generator**

Strip all template resolution, variant expansion, and keyed-by evaluation code from `src/ciadmin/generate/worker_pools.py`. The file shrinks from ~920 lines to ~400 lines. What stays:
- `update_resources()` — entry point registered by boot.py
- `make_worker_pool()` — builds tc-admin WorkerPool resource from expanded pool dict
- `get_gcp_provider_config()`, `get_azure_provider_config()`, `get_aws_provider_config()` — cloud-specific config builders
- `generate_pool_variants()` — simplified to just yield each pool as-is (no template/variant expansion, since expand.py already did it)

What goes:
- `resolve_template()`, `apply_template()` — templates resolved by expand.py
- All keyed-by evaluation calls — values already resolved
- Variant multiplication logic — expand.py already produced one entry per pool-group
- The `meta` / YAML anchor handling

- [ ] **Step 6: Simplify clients.py generator**

Strip the `clients-interpreted.yml` project-matching logic from `src/ciadmin/generate/clients.py`. All clients are now pre-expanded in the `clients.yml` cache entry. The `update_resources()` entry point stays but only iterates the flat client dict. Also simplify `src/ciadmin/generate/ciconfig/clients_interpreted.py` so `fetch_all()` returns `[]`.

- [ ] **Step 7: Verify remaining tests pass**

```bash
cd /Users/pmoore/git/fxci-config
python -m pytest tests/ciadmin/ -v
```

Expected: All remaining tests pass (grants, actions, projects, worker images, utils, get). The deleted test files are gone so pytest won't try to run them.

- [ ] **Step 8: Commit**

```bash
cd /Users/pmoore/git/fxci-config
git add baseline/
git add -A
git commit -m "chore: capture baseline, archive old config, simplify generators

baseline/resources.json contains the target output (DO NOT MODIFY).
baseline/old-config/ contains original YAML files for reference only.
Old worker pool/client tests removed (replaced by tests/expand/ later).
Generators simplified: template/variant/keyed-by logic stripped,
cloud provider config builders and update_resources() preserved.
Check files, grants, hooks, and all CI entry points still functional."
```

---

## Phase 1: Foundation (pool-groups + value resolver)

### Task 1: Create pool-groups data model and loader

**Files:**
- Create: `expand/__init__.py`
- Create: `expand/pool_groups.py`
- Create: `pool-groups.yml`
- Test: `tests/expand/conftest.py`
- Test: `tests/expand/test_pool_groups.py`

- [ ] **Step 1: Write failing test for pool-group expansion**

```python
# tests/expand/test_pool_groups.py
import pytest
from expand.pool_groups import load_pool_groups, PoolGroup


def test_expand_trust_domain_with_levels_and_testing():
    """A trust domain with levels [1,2,3] and testing=true produces 4 pool-groups."""
    config = {
        "pool-groups": {
            "gecko": {"levels": [1, 2, 3], "testing": True},
        }
    }
    result = load_pool_groups(config)
    assert "gecko-1" in result
    assert "gecko-2" in result
    assert "gecko-3" in result
    assert "gecko-t" in result
    assert result["gecko-3"].cot is True
    assert result["gecko-1"].cot is False
    assert result["gecko-t"].level == "t"
    assert result["gecko-1"].trust_domain == "gecko"


def test_expand_trust_domain_without_testing():
    """A trust domain without testing=true produces only numbered pool-groups."""
    config = {
        "pool-groups": {
            "mobile": {"levels": [1, 3]},
        }
    }
    result = load_pool_groups(config)
    assert "mobile-1" in result
    assert "mobile-3" in result
    assert "mobile-t" not in result


def test_standalone_pool_group():
    """A standalone pool-group uses its name as-is."""
    config = {
        "pool-groups": {
            "code-coverage": {"levels": ["standalone"]},
        }
    }
    result = load_pool_groups(config)
    assert "code-coverage" in result
    assert result["code-coverage"].trust_domain == "code-coverage"
    assert result["code-coverage"].level == "standalone"
    assert result["code-coverage"].cot is False
```

- [ ] **Step 2: Create expand package and conftest**

```python
# expand/__init__.py
# fxci-config expansion layer
```

```python
# tests/expand/conftest.py
import sys
import os

# Ensure expand package is importable from repo root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/pmoore/git/fxci-config && python -m pytest tests/expand/test_pool_groups.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'expand.pool_groups'`

- [ ] **Step 4: Implement pool_groups.py**

```python
# expand/pool_groups.py
"""Load and expand pool-group definitions from pool-groups.yml."""

import attr
import yaml


@attr.s(frozen=True)
class PoolGroup:
    """A single expanded pool-group with its derived properties."""
    name = attr.ib(type=str)
    trust_domain = attr.ib(type=str)
    level = attr.ib()  # int (1,2,3) or str ("t", "standalone")
    cot = attr.ib(type=bool)


def load_pool_groups(config):
    """Expand pool-group definitions into a dict of {name: PoolGroup}.

    Args:
        config: parsed YAML dict with a "pool-groups" key

    Returns:
        dict mapping pool-group name -> PoolGroup
    """
    result = {}
    for domain, props in config["pool-groups"].items():
        levels = props.get("levels", [])
        testing = props.get("testing", False)

        for level in levels:
            if level == "standalone":
                name = domain
                result[name] = PoolGroup(
                    name=name,
                    trust_domain=domain,
                    level="standalone",
                    cot=False,
                )
            else:
                name = f"{domain}-{level}"
                result[name] = PoolGroup(
                    name=name,
                    trust_domain=domain,
                    level=level,
                    cot=(level == 3),
                )

        if testing:
            name = f"{domain}-t"
            result[name] = PoolGroup(
                name=name,
                trust_domain=domain,
                level="t",
                cot=False,
            )

    return result


def load_pool_groups_from_file(path="pool-groups.yml"):
    """Load pool-groups from a YAML file."""
    with open(path) as f:
        config = yaml.safe_load(f)
    return load_pool_groups(config)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/pmoore/git/fxci-config && python -m pytest tests/expand/test_pool_groups.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Write pool-groups.yml**

Create the actual pool-groups.yml from the data discovered during analysis. The exact pool-group names must match what the current worker-pools.yml generates (45 pool-groups total).

```yaml
# pool-groups.yml
#
# Declares the trust-domain x level matrix. Each trust domain expands
# to pool-groups named {domain}-{level}. Level 3 gets chain-of-trust: trusted.
# Testing pools (domain-t) are generated when testing: true.

pool-groups:
  gecko:
    levels: [1, 2, 3]
    testing: true
  comm:
    levels: [1, 2, 3]
    testing: true
  enterprise:
    levels: [1, 3]
    testing: true
  nss:
    levels: [1, 3]
    testing: true
  translations:
    levels: [1]
    testing: true
  app-services:
    levels: [1, 3]
  mozilla:
    levels: [1, 3]
    testing: true
  mozillavpn:
    levels: [1, 3]
  glean:
    levels: [1, 3]
  mobile:
    levels: [1, 3]
  xpi:
    levels: [1, 3]
  scriptworker:
    levels: [1, 3]
  releng:
    levels: [1, 3]
    testing: true
  relops:
    levels: [1, 3]
  taskgraph:
    levels: [1, 3]
    testing: true
  adhoc:
    levels: [1, 3]
  code-analysis:
    levels: [1, 3]
  code-coverage:
    levels: [standalone]
  code-review:
    levels: [standalone]
```

- [ ] **Step 7: Write test that pool-groups.yml loads and produces all 45 expected pool-groups**

```python
# tests/expand/test_pool_groups.py (append)

def test_pool_groups_yml_produces_all_expected_groups():
    """pool-groups.yml must produce all 45 pool-groups from the current config."""
    import yaml
    with open("pool-groups.yml") as f:
        config = yaml.safe_load(f)
    result = load_pool_groups(config)

    expected = {
        "gecko-1", "gecko-2", "gecko-3", "gecko-t",
        "comm-1", "comm-2", "comm-3", "comm-t",
        "enterprise-1", "enterprise-3", "enterprise-t",
        "nss-1", "nss-3", "nss-t",
        "translations-1", "translations-t",
        "app-services-1", "app-services-3",
        "mozilla-1", "mozilla-3", "mozilla-t",
        "mozillavpn-1", "mozillavpn-3",
        "glean-1", "glean-3",
        "mobile-1", "mobile-3",
        "xpi-1", "xpi-3",
        "scriptworker-1", "scriptworker-3",
        "releng-1", "releng-3", "releng-t",
        "relops-1", "relops-3",
        "taskgraph-1", "taskgraph-3", "taskgraph-t",
        "adhoc-1", "adhoc-3",
        "code-analysis-1", "code-analysis-3",
        "code-coverage", "code-review",
    }
    assert set(result.keys()) == expected
```

- [ ] **Step 8: Run all pool-group tests**

Run: `cd /Users/pmoore/git/fxci-config && python -m pytest tests/expand/test_pool_groups.py -v`
Expected: PASS (4 tests)

- [ ] **Step 9: Commit**

```bash
cd /Users/pmoore/git/fxci-config
git add expand/__init__.py expand/pool_groups.py pool-groups.yml tests/expand/conftest.py tests/expand/test_pool_groups.py
git commit -m "feat: add pool-groups data model and pool-groups.yml"
```

---

### Task 2: Create value resolver (by-level, by-trust-domain, by-cot)

**Files:**
- Create: `expand/resolve.py`
- Test: `tests/expand/test_resolve.py`

- [ ] **Step 1: Write failing tests for value resolution**

```python
# tests/expand/test_resolve.py
import pytest
from expand.pool_groups import PoolGroup
from expand.resolve import resolve_value


@pytest.fixture
def gecko_3():
    return PoolGroup(name="gecko-3", trust_domain="gecko", level=3, cot=True)


@pytest.fixture
def comm_1():
    return PoolGroup(name="comm-1", trust_domain="comm", level=1, cot=False)


@pytest.fixture
def gecko_t():
    return PoolGroup(name="gecko-t", trust_domain="gecko", level="t", cot=False)


def test_plain_value_passes_through(gecko_3):
    assert resolve_value(42, gecko_3) == 42
    assert resolve_value("hello", gecko_3) == "hello"


def test_by_level_exact_match(gecko_3, comm_1):
    value = {"by-level": {3: 500, "default": 1000}}
    assert resolve_value(value, gecko_3) == 500
    assert resolve_value(value, comm_1) == 1000


def test_by_level_testing_pseudo_level(gecko_t):
    value = {"by-level": {"t": 200, "default": 1000}}
    assert resolve_value(value, gecko_t) == 200


def test_by_trust_domain(gecko_3, comm_1):
    value = {"by-trust-domain": {"gecko": 1000, "comm": 300, "default": 100}}
    assert resolve_value(value, gecko_3) == 1000
    assert resolve_value(value, comm_1) == 300


def test_by_cot(gecko_3, comm_1):
    value = {"by-cot": {"trusted": "provider-a", "default": "provider-b"}}
    assert resolve_value(value, gecko_3) == "provider-a"
    assert resolve_value(value, comm_1) == "provider-b"


def test_nested_resolution(gecko_3, comm_1):
    value = {
        "by-trust-domain": {
            "gecko": {"by-level": {3: 500, "default": 1000}},
            "default": 100,
        }
    }
    assert resolve_value(value, gecko_3) == 500
    assert resolve_value(value, comm_1) == 100


def test_resolve_in_dict_recursively(gecko_3):
    """resolve_value should recursively resolve dicts containing by-* keys."""
    value = {
        "max_capacity": {"by-level": {3: 500, "default": 1000}},
        "min_capacity": 0,
    }
    result = resolve_value(value, gecko_3)
    assert result == {"max_capacity": 500, "min_capacity": 0}


def test_missing_key_and_no_default_raises(gecko_3):
    value = {"by-trust-domain": {"comm": 300}}
    with pytest.raises(KeyError):
        resolve_value(value, gecko_3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/pmoore/git/fxci-config && python -m pytest tests/expand/test_resolve.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement resolve.py**

```python
# expand/resolve.py
"""Value resolver for by-level, by-trust-domain, by-cot expressions.

Resolves compressed config values against a PoolGroup's properties.
All by-* dicts resolve to concrete scalars. Supports nesting.
"""

_RESOLVERS = {
    "by-level": lambda pg: pg.level,
    "by-trust-domain": lambda pg: pg.trust_domain,
    "by-cot": lambda pg: "trusted" if pg.cot else "default",
}


def resolve_value(value, pool_group):
    """Resolve a value against a pool-group's properties.

    If value is a dict with a single by-* key, resolve it.
    If value is a plain dict, recursively resolve all values.
    Otherwise return as-is.
    """
    if not isinstance(value, dict):
        return value

    # Check for by-* resolver
    keys = list(value.keys())
    if len(keys) == 1 and keys[0] in _RESOLVERS:
        by_key = keys[0]
        alternatives = value[by_key]
        lookup = _RESOLVERS[by_key](pool_group)

        # Try exact match (convert both to str for level int/str comparison)
        for alt_key, alt_value in alternatives.items():
            if alt_key == "default":
                continue
            if str(alt_key) == str(lookup):
                return resolve_value(alt_value, pool_group)

        # Try default
        if "default" in alternatives:
            return resolve_value(alternatives["default"], pool_group)

        raise KeyError(
            f"No match for {by_key}={lookup!r} in {list(alternatives.keys())} "
            f"and no default (pool-group: {pool_group.name})"
        )

    # Plain dict — recursively resolve all values
    return {k: resolve_value(v, pool_group) for k, v in value.items()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/pmoore/git/fxci-config && python -m pytest tests/expand/test_resolve.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/pmoore/git/fxci-config
git add expand/resolve.py tests/expand/test_resolve.py
git commit -m "feat: add value resolver for by-level, by-trust-domain, by-cot"
```

---

## Phase 2: Worker Pool Expansion

### Task 3: Extract current worker-pools.yml data into compressed format

This is the data analysis task. Read the current 4,009-line worker-pools.yml and produce a compressed version. Break this into sub-steps by cloud provider since they have different config shapes.

**Files:**
- Create: `worker-pools.yml`

- [ ] **Step 1: Extract machine presets (GCP)**

Write an analysis script (one-off, not committed) to extract all unique GCP `machine_type` + disk combinations from the current worker-pools.yml variants. Each unique combination becomes a named machine preset.

Run: `cd /Users/pmoore/git/fxci-config && python extract_machines.py`
Expected: ~15-20 unique GCP machine presets

- [ ] **Step 2: Extract machine presets (Azure)**

Extend the script to extract Azure `vmSize` + location + storage profile combinations. Azure pools use fundamentally different config: `locations` (not regions), `vmSizes` (not instance_types), and optional ARM deployment templates.

Expected: ~5-10 Azure presets

- [ ] **Step 3: Extract templates from worker-defaults**

The current `worker-defaults` section (~300 lines) has per-implementation worker-config blocks (`by-implementation: docker-worker/generic-worker/etc`). Map each implementation's config into the corresponding template in the compressed format. Each template declares its implementation and inherits the worker-config.

- [ ] **Step 4: Compress GCP pools**

For each of the ~75 GCP pool entries:
1. Map variant pool-groups to trust-domain group references
2. Map instance_types/disks to machine presets from Step 1
3. Convert `by-pool-group` regex patterns to `by-level`/`by-trust-domain`/`by-cot` form
4. Identify values requiring `overrides`

Write the GCP pools section of `worker-pools.yml`.

- [ ] **Step 5: Compress Azure and standalone pools**

For the remaining ~21 Azure/standalone pool entries, apply the same compression using Azure presets from Step 2. Include `cloud: azure` in machine presets or pool definitions.

- [ ] **Step 6: Assemble complete worker-pools.yml**

Combine `defaults`, `templates`, `machines`, and `pools` sections. Include the `worker-defaults-passthrough` section for any worker-defaults content that must pass through to ciadmin unchanged.

- [ ] **Step 7: Manual review and commit**

Review the compressed file. Every pool must be representable. Cross-check pool count: 96 pool entries.

```bash
cd /Users/pmoore/git/fxci-config
git add worker-pools.yml
git commit -m "feat: create compressed worker-pools format (96 pools)"
```

---

### Task 4: Implement worker pool expansion

**Files:**
- Create: `expand/worker_pools.py`
- Test: `tests/expand/test_worker_pools.py`

- [ ] **Step 1: Write failing test for simple pool expansion**

```python
# tests/expand/test_worker_pools.py
import pytest
from expand.pool_groups import load_pool_groups, PoolGroup
from expand.worker_pools import expand_worker_pools


@pytest.fixture
def pool_groups():
    config = {
        "pool-groups": {
            "gecko": {"levels": [1, 3]},
        }
    }
    return load_pool_groups(config)


def test_expand_simple_pool(pool_groups):
    """A pool with groups: [gecko] expands to one pool per level."""
    config = {
        "defaults": {},
        "templates": {},
        "machines": {
            "build-std": {
                "machine_type": "n2-standard-4",
                "disks": [{"type": "boot", "size_gb": 75}],
            },
        },
        "pools": {
            "b-linux": {
                "template": None,
                "groups": ["gecko"],
                "machine": "build-std",
                "description": "Linux build",
                "owner": "test@example.com",
                "email_on_error": True,
                "provider": "gcp",
                "image": "test-image",
            },
        },
    }
    result = expand_worker_pools(config, pool_groups)
    pool_ids = [p["pool_id"] for p in result]
    assert "gecko-1/b-linux" in pool_ids
    assert "gecko-3/b-linux" in pool_ids
    assert len(result) == 2


def test_expand_pool_with_specific_pool_groups(pool_groups):
    """A pool referencing specific pool-group names uses them as-is."""
    config = {
        "defaults": {},
        "templates": {},
        "machines": {"m": {"machine_type": "n2-standard-4", "disks": []}},
        "pools": {
            "t-test": {
                "groups": ["gecko-1"],
                "machine": "m",
                "description": "Test",
                "owner": "test@example.com",
                "provider": "gcp",
                "image": "img",
            },
        },
    }
    result = expand_worker_pools(config, pool_groups)
    assert len(result) == 1
    assert result[0]["pool_id"] == "gecko-1/t-test"


def test_expand_pool_with_by_level(pool_groups):
    """by-level values resolve to concrete values per pool-group."""
    config = {
        "defaults": {},
        "templates": {},
        "machines": {"m": {"machine_type": "n2-standard-4", "disks": []}},
        "pools": {
            "b-linux": {
                "groups": ["gecko"],
                "machine": "m",
                "description": "Test",
                "owner": "test@example.com",
                "provider": "gcp",
                "image": "img",
                "max_capacity": {"by-level": {3: 500, "default": 1000}},
            },
        },
    }
    result = expand_worker_pools(config, pool_groups)
    by_id = {p["pool_id"]: p for p in result}
    assert by_id["gecko-3/b-linux"]["config"]["maxCapacity"] == 500
    assert by_id["gecko-1/b-linux"]["config"]["maxCapacity"] == 1000


def test_expand_pool_with_overrides(pool_groups):
    """Overrides apply per-pool-group values after rule resolution."""
    config = {
        "defaults": {},
        "templates": {},
        "machines": {"m": {"machine_type": "n2-standard-4", "disks": []}},
        "pools": {
            "b-linux": {
                "groups": ["gecko"],
                "machine": "m",
                "description": "Test",
                "owner": "test@example.com",
                "provider": "gcp",
                "image": "img",
                "max_capacity": 1000,
                "overrides": {
                    "gecko-1": {"max_capacity": 2000},
                },
            },
        },
    }
    result = expand_worker_pools(config, pool_groups)
    by_id = {p["pool_id"]: p for p in result}
    assert by_id["gecko-1/b-linux"]["config"]["maxCapacity"] == 2000
    assert by_id["gecko-3/b-linux"]["config"]["maxCapacity"] == 1000


def test_expand_pool_with_template(pool_groups):
    """Template config is deep-merged with pool config; pool wins on conflict."""
    config = {
        "defaults": {},
        "templates": {
            "gcp-d2g": {
                "provider": "gcp",
                "implementation": "generic-worker/docker-engine-d2g",
                "worker-config": {"shutdown": {"enabled": True, "afterIdleSeconds": 120}},
            },
        },
        "machines": {"m": {"machine_type": "n2-standard-4", "disks": []}},
        "pools": {
            "b-linux": {
                "template": "gcp-d2g",
                "groups": ["gecko-1"],
                "machine": "m",
                "description": "Test",
                "owner": "test@example.com",
                "image": "img",
                "worker-config": {"shutdown": {"afterIdleSeconds": 60}},
            },
        },
    }
    result = expand_worker_pools(config, pool_groups)
    assert len(result) == 1
    # Template provides provider
    assert result[0]["provider_id"] is not None
    # Pool overrides afterIdleSeconds but inherits enabled from template


def test_expand_azure_pool(pool_groups):
    """Azure pools produce Azure-compatible config (vmSizes, locations)."""
    config = {
        "defaults": {},
        "templates": {},
        "machines": {
            "az-test": {
                "cloud": "azure",
                "vm_size": "Standard_F8s_v2",
                "locations": ["eastus", "westus"],
            },
        },
        "pools": {
            "t-win10-64": {
                "groups": ["gecko-1"],
                "machine": "az-test",
                "description": "Windows test",
                "owner": "test@example.com",
                "provider": "azure",
                "image": "gw-win10",
            },
        },
    }
    result = expand_worker_pools(config, pool_groups)
    assert len(result) == 1
    # Azure config should use vmSizes, not instance_types
    pool_config = result[0]["config"]
    # Verify cloud-specific structure is present


def test_expand_multi_axis_variant(pool_groups):
    """Pools with suffix variants produce multiple pools per pool-group."""
    config = {
        "defaults": {},
        "templates": {},
        "machines": {
            "m-std": {"machine_type": "n2-standard-4", "disks": []},
            "m-large": {"machine_type": "n2-standard-8", "disks": []},
        },
        "pools": {
            "b-linux{suffix}": {
                "groups": [
                    {"gecko": {"machine": "m-std", "suffix": ""}},
                    {"gecko": {"machine": "m-large", "suffix": "-large"}},
                ],
                "description": "Linux build",
                "owner": "test@example.com",
                "provider": "gcp",
                "image": "img",
            },
        },
    }
    result = expand_worker_pools(config, pool_groups)
    pool_ids = sorted(p["pool_id"] for p in result)
    # gecko levels [1,3] x 2 suffix variants = 4 pools
    assert "gecko-1/b-linux" in pool_ids
    assert "gecko-1/b-linux-large" in pool_ids
    assert "gecko-3/b-linux" in pool_ids
    assert "gecko-3/b-linux-large" in pool_ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/pmoore/git/fxci-config && python -m pytest tests/expand/test_worker_pools.py -v`
Expected: FAIL

- [ ] **Step 3: Implement expand/worker_pools.py**

Implement `expand_worker_pools(config, pool_groups)` that:
1. Resolves machine presets to concrete disk/instance_type configs
2. Expands groups to pool-group names (trust-domain → all levels, specific name → as-is)
3. For each pool-group, resolves all by-* values using `resolve_value()`
4. Applies overrides
5. Merges templates
6. Outputs list of dicts in ciadmin WorkerPool format:
   - `pool_id`: `{pool-group}/{worker-type}`
   - `description`, `owner`, `email_on_error`
   - `provider_id` (resolved from by-cot or explicit)
   - `config`: the full provider config (instance_types/vmSizes, regions, etc.)
   - `attributes`: `{}`
   - `variants`: `[{}]`
   - `template`: `null`

This is the most complex function. Build incrementally — start with GCP pools, then extend to Azure/AWS.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/pmoore/git/fxci-config && python -m pytest tests/expand/test_worker_pools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/pmoore/git/fxci-config
git add expand/worker_pools.py tests/expand/test_worker_pools.py
git commit -m "feat: implement worker pool expansion from compressed format"
```

---

### Task 5: Build validate.py and iterate to convergence

**Files:**
- Create: `validate.py`
- Create: `accepted-diffs.json`
- Test: `tests/expand/test_validate.py`

- [ ] **Step 1: Write validate.py**

```python
# validate.py
"""Compare expanded config against baseline resources.

Usage:
    python validate.py [--baseline baseline/resources.json]

Loads compressed config, runs expand.py, feeds into ciadmin generators,
and compares output against the baseline JSON. Reports categorized diffs.
"""
```

The validation flow:
1. Load compressed YAML files
2. Call `expand_worker_pools()` to produce expanded worker-pools data
3. Write to a temp expanded `worker-pools.yml`
4. Invoke ciadmin's `update_resources()` (or equivalent) to generate WorkerPool resources
5. Serialize and compare against baseline
6. Filter out accepted diffs from `accepted-diffs.json`
7. Report remaining diffs

- [ ] **Step 2: Write a basic test for validate.py**

```python
# tests/expand/test_validate.py
def test_validate_reports_diffs():
    """validate should identify differences between expanded and baseline."""
    # Test with a small synthetic baseline and config
    pass  # Implementation depends on validate.py interface
```

- [ ] **Step 3: Run validate.py against baseline**

Run: `cd /Users/pmoore/git/fxci-config && python validate.py --baseline baseline/resources.json`
Expected: Many diffs initially. This starts the convergence loop.

- [ ] **Step 4: Iterate: fix expansion logic, re-validate**

This is iterative work. Triage each diff into one of three categories (see spec, Validation section):
- **Bug in original config** — inconsistency in current YAML. Fix by updating the baseline expectation.
- **Innocuous difference** — ordering, whitespace, formatting. Add to `accepted-diffs.json`.
- **Real regression** — expansion logic error. Fix in `expand/worker_pools.py` or `worker-pools.yml`.

Loop:
- Run validate.py, examine diffs
- Categorize and fix or accept each diff
- Re-run validate.py
- Repeat until all worker pool diffs are resolved or accepted

- [ ] **Step 5: Commit converged worker pool expansion**

```bash
cd /Users/pmoore/git/fxci-config
git add -A
git commit -m "feat: worker pool expansion converges with baseline"
```

---

## Phase 3: Client Expansion

### Task 7: Analyze and compress clients.yml

**Files:**
- Create: `clients.yml`

- [ ] **Step 1: Analyze current clients.yml and clients-interpreted.yml**

Write an analysis script to:
- Group the 116 scriptworker clients by function/env and extract the cross-product pattern
- Group the 28 autophone clients and extract the shared scopes + device list
- Group the 55 generic-worker clients by platform pattern
- Identify one-off clients

- [ ] **Step 2: Write compressed clients.yml**

Create `clients.yml` with:
- `scriptworker-clients` cross-product entries
- `autophone-clients` with base_scopes + device list
- `generic-worker-clients` grouped by platform
- `clients` section for one-offs

- [ ] **Step 3: Commit**

```bash
cd /Users/pmoore/git/fxci-config
git add clients.yml
git commit -m "feat: create compressed clients format"
```

---

### Task 8: Implement client expansion

**Files:**
- Create: `expand/clients.py`
- Test: `tests/expand/test_clients.py`

- [ ] **Step 1: Write failing test for scriptworker client expansion**

```python
# tests/expand/test_clients.py
from expand.clients import expand_clients


def test_expand_scriptworker_clients():
    config = {
        "scriptworker-clients": [
            {
                "function": "addon",
                "envs": ["dev", "prod"],
                "pool-groups": ["gecko-1", "gecko-3"],
            },
        ],
        "autophone-clients": {"base_scopes": [], "devices": []},
        "generic-worker-clients": {},
        "clients": {},
    }
    result = expand_clients(config)
    expected_ids = [
        "project/releng/scriptworker/v2/addon/dev/firefoxci-gecko-1",
        "project/releng/scriptworker/v2/addon/dev/firefoxci-gecko-3",
        "project/releng/scriptworker/v2/addon/prod/firefoxci-gecko-1",
        "project/releng/scriptworker/v2/addon/prod/firefoxci-gecko-3",
    ]
    assert sorted(result.keys()) == sorted(expected_ids)
    # Each client should have correct scopes
    c = result["project/releng/scriptworker/v2/addon/dev/firefoxci-gecko-1"]
    assert "queue:claim-work:scriptworker-k8s/gecko-1-addon-dev" in c["scopes"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/pmoore/git/fxci-config && python -m pytest tests/expand/test_clients.py -v`
Expected: FAIL

- [ ] **Step 3: Implement expand/clients.py**

Implement `expand_clients(config)` that:
1. Expands scriptworker cross-products with correct client IDs and scopes
2. Expands autophone devices with shared base scopes + per-device queue scope
3. Expands generic-worker clients by platform
4. Passes through one-off clients
5. Returns flat dict matching ciadmin `Client.fetch_all()` format

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/pmoore/git/fxci-config && python -m pytest tests/expand/test_clients.py -v`
Expected: PASS

- [ ] **Step 5: Add client expansion to expand.py and validate**

Update `expand.py` to also expand clients. Run validate.py to compare client resources against baseline.

- [ ] **Step 6: Iterate to convergence on clients**

Same convergence loop as worker pools — fix expansion, fix compressed config, accept innocuous diffs.

- [ ] **Step 7: Commit**

```bash
cd /Users/pmoore/git/fxci-config
git add expand/clients.py tests/expand/test_clients.py expand.py clients.yml
git commit -m "feat: implement client expansion from compressed format"
```

---

## Phase 4: Project Defaults

### Task 9: Compress and expand projects.yml

**Files:**
- Create: `projects.yml`
- Create: `expand/projects.py`
- Test: `tests/expand/test_projects.py`

- [ ] **Step 1: Analyze current projects.yml for common feature sets**

Write analysis script to find groups of projects sharing the same features dict. These become project-defaults.

- [ ] **Step 2: Write projects.yml with project-defaults**

Create compressed version with `project-defaults` section and `features+` merge syntax.

- [ ] **Step 3: Write failing test for project defaults merging**

```python
# tests/expand/test_projects.py
from expand.projects import expand_projects


def test_project_inherits_defaults():
    config = {
        "project-defaults": {
            "gecko-hg": {
                "repo_type": "hg",
                "features": {"gecko-roles": True, "hg-push": True},
            },
        },
        "projects": {
            "mozilla-central": {
                "defaults": "gecko-hg",
                "repo": "https://hg.mozilla.org/mozilla-central",
                "trust_domain": "gecko",
                "access": "scm_level_3",
                "features+": {"scriptworker": True},
                "branches": [{"name": "*"}, {"name": "default"}],
            },
        },
    }
    result = expand_projects(config)
    mc = result["mozilla-central"]
    assert mc["repo_type"] == "hg"
    assert mc["features"]["gecko-roles"] is True
    assert mc["features"]["hg-push"] is True
    assert mc["features"]["scriptworker"] is True
    assert "defaults" not in mc
    assert "features+" not in mc
```

- [ ] **Step 4: Write test for extends chains in project-defaults**

```python
def test_project_defaults_extends_chain():
    config = {
        "project-defaults": {
            "base-hg": {
                "repo_type": "hg",
                "features": {"hg-push": True},
            },
            "gecko-hg": {
                "extends": "base-hg",
                "features+": {"gecko-roles": True},
            },
        },
        "projects": {
            "test-proj": {
                "defaults": "gecko-hg",
                "repo": "https://example.com/test",
                "trust_domain": "gecko",
                "branches": [],
            },
        },
    }
    result = expand_projects(config)
    proj = result["test-proj"]
    # Inherited from base-hg
    assert proj["repo_type"] == "hg"
    assert proj["features"]["hg-push"] is True
    # Added by gecko-hg
    assert proj["features"]["gecko-roles"] is True
```

- [ ] **Step 5: Implement expand/projects.py**

Implement `expand_projects(config)` that:
1. Resolves `extends` chains in project-defaults (recursive, depth-limited)
2. Merges defaults into each project
3. Handles `features+` additive merge (custom YAML post-processing — `+` suffix means merge, without `+` means replace)
4. Returns dict matching ciadmin `Project.fetch_all()` format

- [ ] **Step 5: Run tests, validate against baseline, iterate**

- [ ] **Step 6: Add to expand.py and commit**

```bash
cd /Users/pmoore/git/fxci-config
git add expand/projects.py tests/expand/test_projects.py expand.py projects.yml
git commit -m "feat: implement project defaults expansion"
```

---

## Phase 5: Wire Up and Cutover

### Task 10: Write expand.py entry point and wire into tc-admin.py

The expansion layer uses cache injection: `expand.py` reads normalized YAML files (worker-pools.yml, clients.yml, projects.yml), expands them, and populates ciadmin's `get._cache` dict before generators run. The original flat files (clients-interpreted.yml) are removed.

**Files:**
- Create: `expand.py` (entry point)
- Modify: `tc-admin.py`

- [ ] **Step 1: Write expand.py entry point**

```python
# expand.py
"""Expand compressed config and inject into ciadmin's config cache.

Reads: pool-groups.yml, worker-pools.yml, clients.yml,
       projects.yml
Injects into: ciadmin.generate.ciconfig.get._cache

Must be called before ciadmin boot().
"""
import yaml
from expand.pool_groups import load_pool_groups_from_file
from expand.worker_pools import expand_worker_pools
from expand.clients import expand_clients
from expand.projects import expand_projects


def expand_all():
    """Expand all compressed config and inject into ciadmin cache."""
    pool_groups = load_pool_groups_from_file("pool-groups.yml")

    # Expand worker pools
    with open("worker-pools.yml") as f:
        wp_config = yaml.safe_load(f)
    expanded_pools = expand_worker_pools(wp_config, pool_groups)

    # Expand clients
    with open("clients.yml") as f:
        cl_config = yaml.safe_load(f)
    expanded_clients = expand_clients(cl_config)

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
    get._cache["clients-interpreted.yml"] = []  # empty list — all clients pre-expanded
    get._cache["projects.yml"] = expanded_projects


if __name__ == "__main__":
    expand_all()
    print(f"Cache populated: {list(get._cache.keys())}")
```

- [ ] **Step 2: Write integration test for expand_all + ciadmin constructors**

```python
# tests/expand/test_integration.py
"""Verify expanded output matches baseline resource structure."""
import json
import pytest
from expand import expand_all
from ciadmin.generate.ciconfig import get


def test_expanded_worker_pools_have_correct_structure():
    """Each expanded pool dict must have the required fields."""
    expand_all()
    wp_data = get._cache["worker-pools.yml"]
    for pool_info in wp_data["pools"]:
        assert "pool_id" in pool_info
        assert "/" in pool_info["pool_id"], f"pool_id must be provisionerId/workerType: {pool_info['pool_id']}"
        assert pool_info.get("variants") == [{}]
        assert pool_info.get("template") is None
        assert pool_info.get("attributes") == {}
        assert "description" in pool_info
        assert "config" in pool_info
    get._cache.clear()


def test_expanded_clients_have_correct_structure():
    """Each expanded client must have description and scopes."""
    expand_all()
    cl_data = get._cache["clients.yml"]
    for client_id, info in cl_data.items():
        assert "scopes" in info, f"Client {client_id} missing scopes"
        assert isinstance(info["scopes"], list)
        assert "description" in info
    get._cache.clear()


def test_expanded_pool_count_matches_baseline():
    """Number of expanded pools must match baseline."""
    with open("baseline/resources.json") as f:
        baseline = json.load(f)
    baseline_pool_count = sum(1 for r in baseline["resources"] if r["kind"] == "WorkerPool")

    expand_all()
    wp_data = get._cache["worker-pools.yml"]
    assert len(wp_data["pools"]) == baseline_pool_count
    get._cache.clear()
```

- [ ] **Step 3: Modify tc-admin.py**

```python
# tc-admin.py
import os
import sys

sys.path.insert(0, os.path.abspath("./src"))
sys.path.insert(0, os.path.abspath("."))

from expand import expand_all  # noqa: E402
expand_all()

from ciadmin.boot import boot  # noqa: E402
boot()
```

- [ ] **Step 4: Commit**

```bash
cd /Users/pmoore/git/fxci-config
git add expand.py tests/expand/test_integration.py tc-admin.py
git commit -m "feat: wire expand.py into tc-admin.py via cache injection"
```

---

### Task 11: Remove original config files and validate

- [ ] **Step 1: Remove original files**

```bash
cd /Users/pmoore/git/fxci-config
git rm worker-pools.yml clients.yml clients-interpreted.yml projects.yml
git commit -m "chore: remove original config files (replaced by compressed + expansion)"
```

- [ ] **Step 2: Run full tc-admin generate**

Run: `cd /Users/pmoore/git/fxci-config && python tc-admin.py generate --environment firefoxci`
Expected: Same resources as baseline (ciadmin reads from cache, not disk)

- [ ] **Step 3: Run existing test suite**

Run: `cd /Users/pmoore/git/fxci-config && python -m pytest tests/ -v`
Expected: All existing tests pass (they use `mock_ciconfig_file` fixture, not disk reads)

- [ ] **Step 4: Run full validation**

Run: `cd /Users/pmoore/git/fxci-config && python validate.py --baseline baseline/resources.json`
Expected: Zero unresolved diffs

---

### Task 12: Final validation and PR

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/pmoore/git/fxci-config && python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 2: Run validate.py one final time**

Run: `cd /Users/pmoore/git/fxci-config && python validate.py --baseline baseline/resources.json`
Expected: Clean (all diffs accepted or resolved)

- [ ] **Step 3: Verify line counts**

```bash
cd /Users/pmoore/git/fxci-config
echo "--- Config files ---"
wc -l pool-groups.yml worker-pools.yml clients.yml projects.yml hooks.yml
echo "--- Expansion code ---"
find expand/ -name '*.py' | xargs wc -l
echo "--- Tests ---"
find tests/expand/ -name '*.py' | xargs wc -l
```

Expected: Config total ~1,700 lines (down from 8,282)

- [ ] **Step 4: Create draft PR**

```bash
cd /Users/pmoore/git/fxci-config
gh pr create --draft --title "Normalize config: 79% reduction via expansion layer" --body "..."
```
