# Config Maintenance Guide

How to add, modify, and remove worker pools, clients, projects, and pool-groups
in the normalized fxci-config system.

## 1. Overview

Configuration flows through a pipeline:

```
worker-pools.yml  ─┐
pool-groups.yml   ─┤  expand/*.py   ─►  ciadmin  ─►  Taskcluster API
clients.yml       ─┤  (expansion)       (apply)
projects.yml      ─┘
```

**The 4 config files:**

| File | Controls |
|------|----------|
| `pool-groups.yml` | Trust-domain x level matrix (e.g. gecko-1, gecko-3, comm-t) |
| `worker-pools.yml` | Worker pool definitions: templates, machines, capacity |
| `clients.yml` | Taskcluster client credentials and scopes |
| `projects.yml` | Repository definitions, features, and trust domains |

**Pool-groups** are the glue. Each pool-group is a trust-domain at a level
(e.g. `gecko-3`, `comm-1`). Level 3 gets `chain-of-trust: trusted`. Domains
with `testing: true` also generate a `-t` pool-group for dep/test signing.

Worker pools reference pool-groups via `groups`. A pool with
`groups: [gecko, comm]` expands into separate pools for every level defined
in those trust domains (gecko-1, gecko-2, gecko-3, comm-1, comm-2, comm-3).

## 2. How to: Add a new worker pool

### Step-by-step example

Suppose you need a new Linux build pool for the `gecko` and `enterprise`
trust domains on GCP.

**1. Choose a template** from the `templates:` section of `worker-pools.yml`.
Common templates:

- `gcp-d2g-cot` -- GCP with generic-worker d2g (docker-in-generic-worker)
- `gcp-docker-cot` -- GCP with docker-worker
- `gcp-tester` -- GCP tester (level-1 only, no chain-of-trust switching)

**2. Add the pool entry** under `pools:`:

```yaml
- pool_id: b-linux-example
  template: gcp-d2g-cot
  groups: [gecko, enterprise]
  machine: c2-standard-16-2lssd-60gb
  maxCapacity:
    by-trust-domain:
      gecko: 500
      default: 50
```

**3. Understand `groups`.**
Use trust-domain names to include all levels:

```yaml
groups: [gecko, comm]        # expands to gecko-1, gecko-2, gecko-3, comm-1, comm-2, comm-3
```

Use specific pool-groups to target individual levels:

```yaml
groups: [gecko-1, gecko-3]   # only those two pool-groups
```

**4. Pick a machine preset** from the `machines:` section. Each preset is a
short name mapping to a machine spec string:

```yaml
machines:
  c2-standard-16-2lssd-60gb: "c2-standard-16 boot:60 lssd:2 cpu:Intel Cascadelake"
  n2-standard-32-4lssd-60gb: "n2-standard-32 boot:60 lssd:4 cpu:Intel Cascadelake"
```

**5. Use `by-level` / `by-trust-domain`** for values that vary:

```yaml
maxCapacity:
  by-trust-domain:
    gecko: 1000
    comm: 300
    default: 100

provider_id:
  by-level:
    1: fxci-level1-gcp
    3: fxci-level3-gcp
```

These resolve per pool-group during expansion. A `default` key acts as
the fallback.

**6. Validate** (see section 7).

### Using suffixes for size variants

Add `suffixes` to create multiple related pools from one entry:

```yaml
- pool_id: 'b-linux-docker{suffix}-amd'
  template: gcp-d2g-cot
  suffixes:
    '':
      groups: [gecko, comm]
      machine: c3d-standard-16-lssd
    '-large':
      groups: [gecko, comm]
      machine: c3d-standard-30-lssd
    '-xlarge':
      groups: [gecko]
      machine: c3d-standard-60-lssd
  maxCapacity:
    by-trust-domain:
      gecko: 1000
      comm: 300
      default: 100
```

This creates `b-linux-docker-amd`, `b-linux-docker-large-amd`, and
`b-linux-docker-xlarge-amd`, each potentially with different groups and
machine sizes.

## 3. How to: Add a new pool-group / trust domain

Edit `pool-groups.yml`. Each entry declares which levels exist and whether
to generate testing (`-t`) pool-groups:

```yaml
pool-groups:
  my-domain:
    levels: [1, 3]
    testing: true      # generates my-domain-t
```

After adding a new trust domain, you need to:

1. Add pools that reference it (in `worker-pools.yml` via `groups`).
2. Add any clients that need scopes for the new domain (in `clients.yml`).
3. Add projects that use the domain (in `projects.yml` via `trust_domain`).

Special level values: `standalone` creates a pool-group with no numeric
level (used by `code-coverage` and `code-review`).

## 4. How to: Add a new client

`clients.yml` has several sections, each for a different pattern.

### Autophone / device clients

Add a device to the `autophone-clients` section under the appropriate
provider (`bitbar` or `lambda`):

```yaml
autophone-clients:
  bitbar:
    devices:
      - name: gecko-t-bitbar-perf-p9
        queue: gecko-t-bitbar-gw-perf-p9
        description: "Bitbar Google Pixel 9 Phones - Perf Pool"
```

Each device gets the provider's `base-scopes` plus claim-work and worker-id
scopes generated from `queue` and `worker-id-prefix`.

### Scriptworker k8s clients (standard pattern)

Add pool-groups to an existing function's `dev` and/or `prod` lists:

```yaml
scriptworker-k8s-clients:
  beetmover:
    dev: [gecko-1, mobile-1]
    prod:
      - gecko-1
      - gecko-3
      - {pool-group: xpi-3, extra-scopes: [queue:get-artifact:xpi/*]}
```

Entries can be a plain pool-group name (string) or a dict with
`pool-group`, `description`, and `extra-scopes`.

### Scriptworker explicit clients

For clients that don't fit the k8s pattern, add to
`scriptworker-explicit-clients` with full client ID and scopes:

```yaml
scriptworker-explicit-clients:
  project/releng/scriptworker/v2/iscript/prod:
    description: ""
    scopes:
      - assume:worker-type:scriptworker-prov-v1/signing-mac-v1
      - queue:get-artifact:private/openh264/*
```

### One-off clients

For standalone clients that don't fit any pattern, add to `clients:`:

```yaml
clients:
  project/my-project/my-client:
    description: "What this client does"
    scopes:
      - hooks:trigger-hook:project-foo/bar
```

## 5. How to: Add a new project

Edit `projects.yml`. Each project inherits from a default and specifies
its repo, access level, and trust domain.

### Using project-defaults

Pick a default that matches your project type:

| Default | Use for |
|---------|---------|
| `gecko-hg` | Mercurial repos in the gecko trust domain |
| `gecko-hg-cron` | Same, with cron support |
| `gecko-hg-full` | Same, with lando + merge-automation + shipit |
| `git-taskgraph-public` | Git repos with public PR policy |
| `git-taskgraph-collaborators` | Git repos with collaborators-only PRs |
| `app-services-git` | Application-services repos |
| `translations-git` | Firefox Translations repos |

### Adding a project

```yaml
projects:
  my-project:
    defaults: git-taskgraph-public
    repo: https://github.com/mozilla/my-project
    trust_domain: gecko
    branches: ["main@3", "release-*@3"]
```

The `branches` shorthand `"main@3"` expands to `{name: main, level: 3}`.

### Adding features

Use `features+` to add features on top of the defaults (additive merge):

```yaml
  my-project:
    defaults: gecko-hg
    repo: https://hg.mozilla.org/projects/my-project
    access: scm_level_2
    trust_domain: gecko
    features+: [taskgraph-cron]
```

Use plain `features` to replace the defaults entirely. Features can be a
list of strings (all `true`) or a dict for mixed values:

```yaml
features+:
  github-pull-request:
    policy: collaborators
  scriptworker: true
```

### Defaults inheritance

Defaults can extend other defaults with `extends`:

```yaml
project-defaults:
  gecko-hg-cron:
    extends: gecko-hg
    features+: [taskgraph-cron]
```

## 6. Reference: YAML format

### pool-groups.yml

```yaml
pool-groups:
  <trust-domain>:
    levels: [1, 3]        # which levels to generate
    testing: true          # optional; generates <domain>-t pool-groups
```

### worker-pools.yml

Top-level sections: `defaults`, `worker-defaults-passthrough`, `azure-shared`,
`templates`, `machines`, `pools`.

Pool entries in `pools` are either:
- A single pool dict with `pool_id`, `template`, `groups`, `machine`, etc.
- A `pool-table` for multiple similar pools (tabular shorthand)
- A `pool-pair` for d2g/docker-worker variant pairs

### clients.yml

Sections: `autophone-clients`, `scriptworker-k8s-clients`,
`scriptworker-explicit-clients`, `v3-mac-signing-clients`,
`generic-worker-clients`, `clients` (one-off).

### projects.yml

Sections: `project-defaults` (inheritance hierarchy), `projects` (individual
project definitions).

## 7. Validation and testing

Run these from the repo root:

```bash
# Schema validation (catches structural errors before expansion)
uv run python -m expand.validate_schema

# Full expansion (runs the entire pipeline, catches resolution errors)
uv run python validate.py

# Unit tests
uv run pytest tests/expand/ -v
```

Always run all three before submitting a PR.

## 8. Common patterns

### pool-table -- many similar pools

When multiple pools share most fields and differ in only a few columns:

```yaml
- pool-table:
    groups: [translations-1]
    template: translations-d2g
    columns: [pool_id, machine, maxCapacity, description]
    rows:
      - [b-linux-large-gcp-d2g, n2-highmem-32-60gb, 1000, 'Large workers']
      - [b-linux-large-gcp-d2g-1tb, n2-highmem-32-1tb, 1000, 'Extra large workers']
```

Each row becomes a pool entry with the shared fields plus the per-column values.

### pool-pair -- d2g and docker-worker variants

When you need both a d2g pool and a docker-worker pool with shared config:

```yaml
- pool-pair:
    groups: [gecko, comm]
    maxCapacity:
      by-trust-domain:
        gecko: 1000
        comm: 300
        default: 100
    variants:
      - pool_id: b-linux-large
        template: gcp-d2g-cot
        machine: n2-standard-32-4lssd-60gb
      - pool_id: b-linux-large-gcp
        template: gcp-docker-cot
        machine: n2-standard-32-4lssd-20gb
```

Shared fields (groups, maxCapacity) are specified once; per-variant fields are
in each variant dict.

### by-level / by-trust-domain -- variable values

Use `by-level` when a value depends on the security level:

```yaml
provider_id:
  by-level:
    1: fxci-level1-gcp
    3: fxci-level3-gcp
```

Use `by-trust-domain` when it depends on which product:

```yaml
maxCapacity:
  by-trust-domain:
    gecko: 1000
    comm: 300
    default: 100
```

These can be nested:

```yaml
maxCapacity:
  by-trust-domain:
    gecko: 1000
    app-services:
      by-level:
        1: 50
        3: 100
    default: 100
```

Use `by-cot` for chain-of-trust switching (trusted vs untrusted):

```yaml
provider_id:
  by-cot:
    trusted: fxci-level3-gcp
    default: fxci-level1-gcp
```

Always include a `default` key unless you are certain every possible value
is covered.
