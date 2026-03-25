"""Tests for expand/projects.py."""

import os
import yaml
import pytest

from expand.projects import expand_projects, expand_projects_from_file

BASELINE_OLD_CONFIG = "baseline/old-config/projects.yml"
_baseline_missing = not os.path.exists(BASELINE_OLD_CONFIG)


# --- Minimal configs for unit tests ---

SIMPLE_NO_DEFAULTS = {
    "projects": {
        "my-project": {
            "repo": "https://example.com/repo",
            "repo_type": "git",
            "trust_domain": "test",
            "features": {"feat-a": True},
        },
    },
}

SIMPLE_WITH_DEFAULTS = {
    "project-defaults": {
        "base": {
            "repo_type": "hg",
            "features": {
                "feat-a": True,
                "feat-b": True,
            },
        },
    },
    "projects": {
        "proj1": {
            "defaults": "base",
            "repo": "https://example.com/proj1",
            "trust_domain": "test",
        },
    },
}

EXTENDS_CHAIN = {
    "project-defaults": {
        "grandparent": {
            "repo_type": "hg",
            "features": {
                "feat-a": True,
            },
        },
        "parent": {
            "extends": "grandparent",
            "features+": {
                "feat-b": True,
            },
        },
        "child": {
            "extends": "parent",
            "features+": {
                "feat-c": True,
            },
        },
    },
    "projects": {
        "deep-project": {
            "defaults": "child",
            "repo": "https://example.com/deep",
            "trust_domain": "test",
        },
    },
}

FEATURES_PLUS_MERGE = {
    "project-defaults": {
        "base": {
            "repo_type": "git",
            "features": {
                "shared-a": True,
                "shared-b": True,
            },
        },
    },
    "projects": {
        "additive": {
            "defaults": "base",
            "repo": "https://example.com/add",
            "trust_domain": "test",
            "features+": {
                "extra-c": True,
            },
        },
        "replace": {
            "defaults": "base",
            "repo": "https://example.com/replace",
            "trust_domain": "test",
            "features": {
                "only-this": True,
            },
        },
    },
}

FEATURES_PLUS_OVERRIDE = {
    "project-defaults": {
        "base": {
            "repo_type": "git",
            "features": {
                "feat-a": True,
                "feat-b": False,
            },
        },
    },
    "projects": {
        "override": {
            "defaults": "base",
            "repo": "https://example.com/override",
            "trust_domain": "test",
            "features+": {
                "feat-b": True,
                "feat-c": True,
            },
        },
    },
}

BRANCHES_OVERRIDE = {
    "project-defaults": {
        "base": {
            "repo_type": "hg",
            "branches": [{"name": "*"}, {"name": "default"}],
            "features": {"feat-a": True},
        },
    },
    "projects": {
        "custom-branches": {
            "defaults": "base",
            "repo": "https://example.com/custom",
            "trust_domain": "test",
            "branches": [{"name": "*"}],
        },
    },
}


class TestNoDefaults:
    def test_passthrough(self):
        result = expand_projects(SIMPLE_NO_DEFAULTS)
        assert "my-project" in result
        assert result["my-project"]["repo"] == "https://example.com/repo"
        assert result["my-project"]["features"] == {"feat-a": True}

    def test_no_alias_in_value(self):
        result = expand_projects(SIMPLE_NO_DEFAULTS)
        assert "alias" not in result["my-project"]


class TestDefaultInheritance:
    def test_inherits_repo_type(self):
        result = expand_projects(SIMPLE_WITH_DEFAULTS)
        assert result["proj1"]["repo_type"] == "hg"

    def test_inherits_features(self):
        result = expand_projects(SIMPLE_WITH_DEFAULTS)
        assert result["proj1"]["features"] == {"feat-a": True, "feat-b": True}

    def test_project_fields_merged(self):
        result = expand_projects(SIMPLE_WITH_DEFAULTS)
        assert result["proj1"]["repo"] == "https://example.com/proj1"
        assert result["proj1"]["trust_domain"] == "test"

    def test_defaults_key_removed(self):
        result = expand_projects(SIMPLE_WITH_DEFAULTS)
        assert "defaults" not in result["proj1"]


class TestExtendsChain:
    def test_three_level_chain(self):
        result = expand_projects(EXTENDS_CHAIN)
        proj = result["deep-project"]
        assert proj["repo_type"] == "hg"
        assert proj["features"] == {
            "feat-a": True,
            "feat-b": True,
            "feat-c": True,
        }

    def test_circular_extends_raises(self):
        config = {
            "project-defaults": {
                "a": {"extends": "b", "features": {}},
                "b": {"extends": "a", "features": {}},
            },
            "projects": {},
        }
        with pytest.raises(ValueError, match="Circular"):
            expand_projects(config)

    def test_missing_extends_raises(self):
        config = {
            "project-defaults": {
                "a": {"extends": "nonexistent", "features": {}},
            },
            "projects": {},
        }
        with pytest.raises(ValueError, match="Circular|missing"):
            expand_projects(config)


class TestFeaturesMerge:
    def test_features_plus_additive(self):
        result = expand_projects(FEATURES_PLUS_MERGE)
        proj = result["additive"]
        assert proj["features"] == {
            "shared-a": True,
            "shared-b": True,
            "extra-c": True,
        }

    def test_features_replace(self):
        result = expand_projects(FEATURES_PLUS_MERGE)
        proj = result["replace"]
        assert proj["features"] == {"only-this": True}
        assert "shared-a" not in proj["features"]

    def test_features_plus_overrides_values(self):
        result = expand_projects(FEATURES_PLUS_OVERRIDE)
        proj = result["override"]
        assert proj["features"]["feat-a"] is True
        assert proj["features"]["feat-b"] is True  # overridden from False
        assert proj["features"]["feat-c"] is True

    def test_features_plus_without_defaults(self):
        """features+ on a project with no defaults should still work."""
        config = {
            "projects": {
                "standalone": {
                    "repo": "https://example.com/repo",
                    "repo_type": "git",
                    "features+": {"new-feat": True},
                },
            },
        }
        result = expand_projects(config)
        assert result["standalone"]["features"] == {"new-feat": True}


class TestBranchesOverride:
    def test_branches_replaced_not_merged(self):
        result = expand_projects(BRANCHES_OVERRIDE)
        proj = result["custom-branches"]
        assert proj["branches"] == [{"name": "*"}]


class TestEmptyConfig:
    def test_empty_returns_empty(self):
        result = expand_projects({})
        assert result == {}

    def test_no_projects_section(self):
        result = expand_projects({"project-defaults": {"base": {"repo_type": "git"}}})
        assert result == {}


class TestUnknownDefaults:
    def test_unknown_defaults_raises(self):
        config = {
            "projects": {
                "bad": {
                    "defaults": "nonexistent",
                    "repo": "https://example.com/bad",
                },
            },
        }
        with pytest.raises(ValueError, match="Unknown defaults"):
            expand_projects(config)


class TestExpandFromFile:
    def test_expand_from_file_count(self):
        """Expand from the real compressed YAML and check count."""
        result = expand_projects_from_file("projects.yml")
        assert len(result) == 75

    @pytest.mark.skipif(_baseline_missing, reason="baseline/old-config/projects.yml not present")
    def test_expand_from_file_matches_baseline(self):
        """Verify all 75 projects match the old projects.yml exactly."""
        result = expand_projects_from_file("projects.yml")
        with open(BASELINE_OLD_CONFIG) as f:
            old = yaml.safe_load(f)

        assert set(result.keys()) == set(old.keys()), (
            f"Project alias mismatch: "
            f"missing={sorted(old.keys() - result.keys())}, "
            f"extra={sorted(result.keys() - old.keys())}"
        )

        for alias in sorted(result.keys()):
            old_proj = old[alias]
            new_proj = result[alias]
            all_keys = set(old_proj.keys()) | set(new_proj.keys())
            for key in sorted(all_keys):
                assert old_proj.get(key) == new_proj.get(key), (
                    f"{alias}.{key}: "
                    f"old={old_proj.get(key)!r}, "
                    f"new={new_proj.get(key)!r}"
                )

    def test_no_defaults_key_in_expanded(self):
        """Ensure 'defaults' is stripped from all expanded projects."""
        result = expand_projects_from_file("projects.yml")
        for alias, proj in result.items():
            assert "defaults" not in proj, f"{alias} still has 'defaults' key"
            assert "features+" not in proj, f"{alias} still has 'features+' key"
