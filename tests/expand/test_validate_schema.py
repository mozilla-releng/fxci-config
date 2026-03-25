"""Tests for expand/validate_schema.py — config YAML schema validation."""

import os
import sys

import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from expand.validate_schema import (
    validate_clients,
    validate_pool_groups,
    validate_projects,
    validate_schemas,
    validate_worker_pools,
)


# ── pool-groups.yml ─────────────────────────────────────────────────────────


def test_pool_groups_valid():
    config = {
        "pool-groups": {
            "gecko": {"levels": [1, 2, 3], "testing": True},
            "code-coverage": {"levels": ["standalone"]},
        }
    }
    assert validate_pool_groups(config) == []


def test_pool_groups_missing_key():
    errors = validate_pool_groups({})
    assert any("missing required key 'pool-groups'" in e for e in errors)


def test_pool_groups_missing_levels():
    config = {"pool-groups": {"gecko": {"testing": True}}}
    errors = validate_pool_groups(config)
    assert any("missing required field 'levels'" in e for e in errors)


def test_pool_groups_unknown_field():
    config = {"pool-groups": {"gecko": {"levels": [1], "unknown_field": True}}}
    errors = validate_pool_groups(config)
    assert any("unknown field 'unknown_field'" in e for e in errors)


def test_pool_groups_invalid_level():
    config = {"pool-groups": {"gecko": {"levels": [1, "bad"]}}}
    errors = validate_pool_groups(config)
    assert any("must be int or 'standalone'" in e for e in errors)


# ── worker-pools.yml ────────────────────────────────────────────────────────


def _minimal_wp_config(**overrides):
    """Return a minimal valid worker-pools config."""
    base = {
        "pools": [{"pool_id": "test/pool"}],
    }
    base.update(overrides)
    return base


def test_worker_pools_valid():
    config = {
        "pools": [{"pool_id": "infra/build-decision", "maxCapacity": 4}],
        "templates": {},
        "machines": {},
    }
    assert validate_worker_pools(config) == []


def test_worker_pools_missing_pools():
    errors = validate_worker_pools({"defaults": {}})
    assert any("missing required key 'pools'" in e for e in errors)


def test_worker_pools_unknown_top_level():
    config = {"pools": [], "unknwn": 1}
    errors = validate_worker_pools(config)
    assert any("unknown top-level key 'unknwn'" in e for e in errors)


def test_worker_pools_missing_pool_id():
    config = {"pools": [{"maxCapacity": 10}]}
    errors = validate_worker_pools(config)
    assert any("missing required field 'pool_id'" in e for e in errors)


def test_worker_pools_unknown_pool_field_with_suggestion():
    config = {"pools": [{"pool_id": "x/y", "descrption": "typo"}]}
    errors = validate_worker_pools(config)
    assert any("unknown field 'descrption'" in e for e in errors)
    assert any("did you mean" in e and "'description'" in e for e in errors)


def test_worker_pools_invalid_template_ref():
    config = {
        "templates": {"gcp-d2g-cot": {"provider": "gcp"}},
        "pools": [{"pool_id": "x/y", "template": "gcp-d2g-cott"}],
    }
    errors = validate_worker_pools(config)
    assert any("unknown template 'gcp-d2g-cott'" in e for e in errors)
    assert any("did you mean" in e and "'gcp-d2g-cot'" in e for e in errors)


def test_worker_pools_invalid_machine_ref():
    config = {
        "machines": {"c2-standard-4-75gb": "c2-standard-4 boot:75"},
        "pools": [{"pool_id": "x/y", "machine": "c2-standard-4-75g"}],
    }
    errors = validate_worker_pools(config)
    assert any("unknown machine preset 'c2-standard-4-75g'" in e for e in errors)


def test_worker_pools_invalid_groups_ref():
    pool_group_names = {"gecko-1", "gecko-3", "gecko-t", "comm-1", "comm-3"}
    config = {
        "pools": [{"pool_id": "test", "groups": ["gecok"]}],
    }
    errors = validate_worker_pools(config, pool_group_names=pool_group_names)
    assert any("unknown pool-group or trust-domain 'gecok'" in e for e in errors)


def test_worker_pools_valid_trust_domain_group():
    """Trust domain names (e.g. 'gecko') are valid in groups."""
    pool_group_names = {"gecko-1", "gecko-3", "gecko-t"}
    config = {
        "pools": [{"pool_id": "test", "groups": ["gecko"]}],
    }
    errors = validate_worker_pools(config, pool_group_names=pool_group_names)
    assert errors == []


def test_worker_pools_template_extends_unknown():
    config = {
        "templates": {
            "child": {"extends": "nonexistent", "provider": "gcp"},
        },
        "pools": [],
    }
    errors = validate_worker_pools(config)
    assert any("unknown template 'nonexistent'" in e for e in errors)


def test_worker_pools_template_circular_extends():
    config = {
        "templates": {
            "a": {"extends": "b"},
            "b": {"extends": "a"},
        },
        "pools": [],
    }
    errors = validate_worker_pools(config)
    assert any("circular extends chain" in e for e in errors)


def test_worker_pools_pool_table_valid():
    config = {
        "pools": [
            {
                "pool-table": {
                    "columns": ["pool_id", "machine"],
                    "rows": [
                        ["p1", "m1"],
                        ["p2", "m2"],
                    ],
                }
            }
        ],
    }
    assert validate_worker_pools(config) == []


def test_worker_pools_pool_table_missing_columns():
    config = {
        "pools": [{"pool-table": {"rows": [["a", "b"]]}}],
    }
    errors = validate_worker_pools(config)
    assert any("missing required field 'columns'" in e for e in errors)


def test_worker_pools_pool_table_row_length_mismatch():
    config = {
        "pools": [
            {
                "pool-table": {
                    "columns": ["pool_id", "machine", "cap"],
                    "rows": [["p1", "m1"]],  # too few
                }
            }
        ],
    }
    errors = validate_worker_pools(config)
    assert any("2 values but 3 columns" in e for e in errors)


def test_worker_pools_pool_pair_valid():
    config = {
        "pools": [{"pool-pair": {"variants": [{"pool_id": "a"}, {"pool_id": "b"}]}}],
    }
    assert validate_worker_pools(config) == []


def test_worker_pools_pool_pair_missing_variants():
    config = {"pools": [{"pool-pair": {"pool_id": "x"}}]}
    errors = validate_worker_pools(config)
    assert any("missing required field 'variants'" in e for e in errors)


def test_worker_pools_group_alias_skipped():
    """Groups starting with @ are aliases and should not be flagged."""
    pool_group_names = {"gecko-1"}
    config = {
        "pools": [{"pool_id": "test", "groups": ["@my-alias"]}],
    }
    errors = validate_worker_pools(config, pool_group_names=pool_group_names)
    assert errors == []


# ── clients.yml ─────────────────────────────────────────────────────────────


def test_clients_valid():
    config = {
        "autophone-clients": {
            "bitbar": {
                "base-scopes": ["auth:sentry:tc-worker-script"],
                "worker-id-prefix": "bitbar",
                "devices": [{"name": "dev1", "queue": "q1"}],
            }
        },
        "single-scope-worker-clients": {
            "worker1": {"worker-type": "wt1", "description": "test"},
        },
    }
    assert validate_clients(config) == []


def test_clients_unknown_top_level():
    config = {"autophone-clients": {}, "unknwn-section": {}}
    errors = validate_clients(config)
    assert any("unknown top-level key 'unknwn-section'" in e for e in errors)


def test_clients_yaml_anchor_keys_ignored():
    """Keys starting with _ (YAML anchors) should not be flagged."""
    config = {"_my_anchor": ["scope1"], "clients": {}}
    errors = validate_clients(config)
    assert not any("_my_anchor" in e for e in errors)


def test_clients_autophone_missing_fields():
    config = {
        "autophone-clients": {
            "bitbar": {"devices": [{"name": "dev1"}]},
        }
    }
    errors = validate_clients(config)
    assert any("missing required field 'base-scopes'" in e for e in errors)
    assert any("missing required field 'worker-id-prefix'" in e for e in errors)
    assert any("missing required field 'queue'" in e for e in errors)


def test_clients_autophone_device_missing_name():
    config = {
        "autophone-clients": {
            "bitbar": {
                "base-scopes": [],
                "worker-id-prefix": "bb",
                "devices": [{"queue": "q1"}],
            }
        }
    }
    errors = validate_clients(config)
    assert any("missing required field 'name'" in e for e in errors)


def test_clients_single_scope_missing_worker_type():
    config = {
        "single-scope-worker-clients": {
            "worker1": {"description": "no worker-type"},
        }
    }
    errors = validate_clients(config)
    assert any("missing required field 'worker-type'" in e for e in errors)


def test_clients_scriptworker_k8s_unknown_env():
    config = {
        "scriptworker-k8s-clients": {
            "addon": {"dev": ["gecko-1"], "staging": ["gecko-1"]},
        }
    }
    errors = validate_clients(config)
    assert any("unknown environment 'staging'" in e for e in errors)


# ── projects.yml ────────────────────────────────────────────────────────────


def test_projects_valid():
    config = {
        "project-defaults": {
            "gecko-hg": {"repo_type": "hg", "features": ["hg-push"]},
        },
        "projects": {
            "ash": {"defaults": "gecko-hg", "repo": "https://hg.mozilla.org/projects/ash"},
        },
    }
    assert validate_projects(config) == []


def test_projects_unknown_top_level():
    config = {"project-defaults": {}, "projects": {}, "extra": {}}
    errors = validate_projects(config)
    assert any("unknown top-level key 'extra'" in e for e in errors)


def test_projects_unknown_defaults_ref():
    config = {
        "project-defaults": {"gecko-hg": {"repo_type": "hg"}},
        "projects": {"ash": {"defaults": "gecko-hgg", "repo": "x"}},
    }
    errors = validate_projects(config)
    assert any("unknown project-default 'gecko-hgg'" in e for e in errors)
    assert any("did you mean" in e and "'gecko-hg'" in e for e in errors)


def test_projects_unknown_field():
    config = {
        "projects": {
            "ash": {"repo": "x", "repo_typo": "hg"},
        }
    }
    errors = validate_projects(config)
    assert any("unknown field 'repo_typo'" in e for e in errors)


def test_projects_default_extends_unknown():
    config = {
        "project-defaults": {
            "child": {"extends": "nonexistent"},
        },
        "projects": {},
    }
    errors = validate_projects(config)
    assert any("unknown default 'nonexistent'" in e for e in errors)


def test_projects_default_circular_extends():
    config = {
        "project-defaults": {
            "a": {"extends": "b"},
            "b": {"extends": "a"},
        },
        "projects": {},
    }
    errors = validate_projects(config)
    assert any("circular extends chain" in e for e in errors)


# ── Integration test: all real config files pass ────────────────────────────


def test_all_config_files_pass_validation():
    """All existing config files in the repo root pass schema validation."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    errors = validate_schemas(base_dir=repo_root)
    assert errors == [], f"Validation errors found:\n" + "\n".join(f"  {e}" for e in errors)
