# fxci-config

## YAML files

Each YAML file in the repo root begins with a comment describing its purpose and schema.
Read that comment before adding or modifying entries. Key files:

- `clients.yml` — static Taskcluster clients (see header)
- `clients-interpreted.yml` — templated clients expanded per trust domain (see header)
- `grants.d/grants.yml` — shared grant definitions (see header for format); per-trust-domain grants live in
  `grants.d/<trust-domain>.yml`
- `projects.yml` — project/repository definitions (see header)
- `worker-pools.yml` — worker pool definitions (see header)
- `environments.yml` — `firefoxci` (production) and `staging` environment configs

## Workflow

1. Make changes in a local clone.
2. Determine which environment applies (options in `environments.yml`; usually `firefoxci`).
3. Run `tc-admin diff --environment=firefoxci` and `tc-admin check --environment=firefoxci`.
4. Submit for review — changes auto-apply to `firefoxci` (production) on landing.

For staging: comment `/taskcluster apply-staging` on the PR to apply, or run
`tc-admin apply --environment=staging` locally. Validate against staging first when
touching scopes, worker configs, or fxci-config itself.

## Verification

Before committing, run `tc-admin diff` to preview the Taskcluster resources that would
change. You need Taskcluster credentials with `auth:list-clients` scope and a GitHub
token to avoid rate limits (see `README.md` "Initial Setup" for `GITHUB_TOKEN`).

```bash
TASKCLUSTER_ROOT_URL=https://firefox-ci-tc.services.mozilla.com \
  taskcluster signin --scope auth:list-clients > $TMPDIR/tc-creds.sh
source $TMPDIR/tc-creds.sh
GITHUB_TOKEN=$(gh auth token) uv run tc-admin diff --environment firefoxci
```
