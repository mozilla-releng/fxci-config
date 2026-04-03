# fxci-config

## YAML files

Each YAML file in the repo root begins with a comment describing its purpose and schema.
Read that comment before adding or modifying entries. Key files:

- `clients.yml` — static Taskcluster clients (see header)
- `clients-interpreted.yml` — templated clients expanded per trust domain (see header)
- `grants.d/grants.yml` — grant schema reference; per-trust-domain grants live in
  `grants.d/<trust-domain>.yml`
- `projects.yml` — project/repository definitions (see header)
- `worker-pools.yml` — worker pool definitions (see header)
- `environments.yml` — `firefoxci` (production) and `staging` environment configs

## Workflow

See `README.md` for the full workflow (setup, diff, check, apply).

## Verification

Before committing, run `ci-admin diff` to preview the Taskcluster resources that would
change. You need Taskcluster credentials with `auth:list-clients` scope and a GitHub
token to avoid rate limits (see `README.md` "Initial Setup" for `GITHUB_TOKEN`).

```bash
TASKCLUSTER_ROOT_URL=https://firefox-ci-tc.services.mozilla.com \
  taskcluster signin --scope auth:list-clients > $TMPDIR/tc-creds.sh
source $TMPDIR/tc-creds.sh
GITHUB_TOKEN=$(gh auth token) uv run ci-admin diff --environment firefoxci
```

## PR template

```markdown
[Bug NNNNN](https://bugzilla.mozilla.org/show_bug.cgi?id=NNNNN)

## Verification

### `<short-sha>` — `<commit-message>`
- `ci-admin diff --environment firefoxci`
  ```
  <relevant diff extract showing the change>
  ```
```

- Always hyperlink the Bugzilla bug at the top of the PR body.
- The Summary section is optional when the PR title already conveys the change.
