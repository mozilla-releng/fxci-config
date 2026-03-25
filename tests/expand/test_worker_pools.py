import pytest
import copy
from expand.pool_groups import PoolGroup, load_pool_groups
from expand.worker_pools import expand_worker_pools, _deep_merge


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_pool_groups():
    """Build a realistic pool_groups dict for tests."""
    config = {
        "pool-groups": {
            "gecko": {"levels": [1, 2, 3], "testing": True},
            "comm": {"levels": [1, 2, 3], "testing": True},
            "app-services": {"levels": [1, 3]},
            "enterprise": {"levels": [1, 3], "testing": True},
            "nss": {"levels": [1, 3], "testing": True},
            "translations": {"levels": [1], "testing": True},
            "mozilla": {"levels": [1, 3], "testing": True},
            "mozillavpn": {"levels": [1, 3]},
            "glean": {"levels": [1, 3]},
            "mobile": {"levels": [1, 3]},
            "xpi": {"levels": [1, 3]},
            "code-review": {"levels": ["standalone"]},
            "code-coverage": {"levels": ["standalone"]},
            "code-analysis": {"levels": [1, 3]},
        }
    }
    return load_pool_groups(config)


def _minimal_config(pools, templates=None, machines=None):
    """Build a minimal compressed config with the given pools."""
    return {
        "defaults": {
            "owner": "test@example.com",
            "email_on_error": True,
            "lifecycle": {"registrationTimeout": 1800},
        },
        "templates": templates or {},
        "machines": machines or {},
        "pools": pools,
    }


# ── Test 1: Simple pool expansion (groups: [gecko] -> one pool per level) ──

def test_simple_pool_expansion_trust_domain():
    """groups: [gecko] expands to gecko-1, gecko-2, gecko-3 (excludes testing)."""
    pool_groups = _make_pool_groups()
    config = _minimal_config(
        pools=[{
            "pool_id": "b-linux",
            "description": "Worker for Firefox automation.",
            "groups": ["gecko"],
            "provider_id": "fxci-level1-gcp",
            "machine": "test-machine",
            "maxCapacity": 100,
        }],
        machines={
            "test-machine": {
                "machine_type": "n2-standard-4",
                "disks": [{"type": "boot", "size_gb": 75}],
            }
        },
    )

    result = expand_worker_pools(config, pool_groups)

    pool_ids = [p["pool_id"] for p in result]
    assert "gecko-1/b-linux" in pool_ids
    assert "gecko-2/b-linux" in pool_ids
    assert "gecko-3/b-linux" in pool_ids
    assert "gecko-t/b-linux" not in pool_ids  # testing excluded from trust-domain expansion
    assert len(result) == 3


# ── Test 2: Specific pool-group names (groups: [gecko-1] -> single pool) ──

def test_specific_pool_group_name():
    """groups: [gecko-1] produces exactly one pool."""
    pool_groups = _make_pool_groups()
    config = _minimal_config(
        pools=[{
            "pool_id": "b-linux-test",
            "description": "Test pool",
            "groups": ["gecko-1"],
            "provider_id": "fxci-level1-gcp",
            "machine": "test-machine",
            "maxCapacity": 50,
        }],
        machines={
            "test-machine": {
                "machine_type": "n2-standard-4",
                "disks": [{"type": "boot", "size_gb": 75}],
            }
        },
    )

    result = expand_worker_pools(config, pool_groups)

    assert len(result) == 1
    assert result[0]["pool_id"] == "gecko-1/b-linux-test"
    assert result[0]["description"] == "Test pool"
    assert result[0]["provider_id"] == "fxci-level1-gcp"


# ── Test 3: Pool with by-level values -> concrete values per pool-group ──

def test_by_level_resolution():
    """by-level values resolve differently for each pool-group."""
    pool_groups = _make_pool_groups()
    config = _minimal_config(
        pools=[{
            "pool_id": "b-linux-medium",
            "description": "Test pool",
            "groups": ["gecko-1", "gecko-2", "gecko-3"],
            "provider_id": "fxci-level1-gcp",
            "machine": "test-machine",
            "maxCapacity": {
                "by-level": {
                    1: 200,
                    2: 50,
                    3: 200,
                    "default": 10,
                }
            },
        }],
        machines={
            "test-machine": {
                "machine_type": "c2-standard-8",
                "disks": [{"type": "boot", "size_gb": 60}],
            }
        },
    )

    result = expand_worker_pools(config, pool_groups)

    by_pool = {p["pool_id"]: p for p in result}
    assert by_pool["gecko-1/b-linux-medium"]["config"]["maxCapacity"] == 200
    assert by_pool["gecko-2/b-linux-medium"]["config"]["maxCapacity"] == 50
    assert by_pool["gecko-3/b-linux-medium"]["config"]["maxCapacity"] == 200


# ── Test 4: Pool with overrides -> per-pool-group override applied ──

def test_by_trust_domain_with_nested_by_level():
    """by-trust-domain + nested by-level resolves correctly."""
    pool_groups = _make_pool_groups()
    config = _minimal_config(
        pools=[{
            "pool_id": "b-linux",
            "description": "Worker",
            "groups": ["gecko", "app-services"],
            "provider_id": "fxci-level1-gcp",
            "machine": "test-machine",
            "maxCapacity": {
                "by-trust-domain": {
                    "gecko": 1000,
                    "app-services": {
                        "by-level": {
                            1: 50,
                            3: 100,
                        }
                    },
                    "default": 100,
                }
            },
        }],
        machines={
            "test-machine": {
                "machine_type": "c2-standard-16",
                "disks": [{"type": "boot", "size_gb": 60}],
            }
        },
    )

    result = expand_worker_pools(config, pool_groups)

    by_pool = {p["pool_id"]: p for p in result}
    # All gecko levels get 1000
    assert by_pool["gecko-1/b-linux"]["config"]["maxCapacity"] == 1000
    assert by_pool["gecko-3/b-linux"]["config"]["maxCapacity"] == 1000
    # app-services varies by level
    assert by_pool["app-services-1/b-linux"]["config"]["maxCapacity"] == 50
    assert by_pool["app-services-3/b-linux"]["config"]["maxCapacity"] == 100


# ── Test 5: Pool with template -> template config merged ──

def test_template_merge():
    """Template properties are merged into the pool, pool overrides template."""
    pool_groups = _make_pool_groups()
    config = _minimal_config(
        pools=[{
            "pool_id": "b-linux",
            "template": "gcp-d2g-cot",
            "description": "Worker",
            "groups": ["gecko-1"],
            "machine": "test-machine",
            "maxCapacity": 500,
        }],
        templates={
            "gcp-d2g-cot": {
                "provider": "gcp",
                "implementation": "generic-worker/linux-d2g",
                "provider_id": {
                    "by-cot": {
                        "trusted": "fxci-level3-gcp",
                        "default": "fxci-level1-gcp",
                    }
                },
                "image": "ubuntu-2404-headless",
                "minCapacity": 0,
                "regions": ["us-central1", "us-west1"],
            }
        },
        machines={
            "test-machine": {
                "machine_type": "c2-standard-16",
                "disks": [{"type": "boot", "size_gb": 60}],
            }
        },
    )

    result = expand_worker_pools(config, pool_groups)

    assert len(result) == 1
    pool = result[0]
    assert pool["pool_id"] == "gecko-1/b-linux"
    # provider_id resolved from template via by-cot (gecko-1 is not cot)
    assert pool["provider_id"] == "fxci-level1-gcp"
    # Image from template
    assert pool["config"]["image"] == "ubuntu-2404-headless"
    # Pool's maxCapacity overrides
    assert pool["config"]["maxCapacity"] == 500
    # Template's minCapacity preserved
    assert pool["config"]["minCapacity"] == 0
    # Template's regions preserved
    assert pool["config"]["regions"] == ["us-central1", "us-west1"]


# ── Test 6: Azure pool -> cloud-specific config preserved ──

def test_azure_pool():
    """Azure pools produce azure-specific config fields."""
    pool_groups = _make_pool_groups()
    config = _minimal_config(
        pools=[{
            "pool_id": "b-win2022-alpha",
            "description": "",
            "owner": "relops@mozilla.com",
            "groups": ["gecko-1"],
            "cloud": "azure",
            "provider_id": "azure2",
            "image": "ronin_b1_windows2022_64_2009_alpha",
            "image_resource_group": "rg-packer-through-cib",
            "implementation": "generic-worker/windows-builder",
            "worker-purpose": "gecko-1",
            "locations": ["central-india"],
            "maxCapacity": 10,
            "vm_size": "Standard_D96ads_v5",
            "spot": True,
            "armDeployment": {"templateSpecId": "some-template-id"},
            "worker-config": {
                "genericWorker": {
                    "config": {"workerType": "win2022-azure"}
                }
            },
            "tags": {
                "sourceScript": "bootstrap.ps1",
                "sourceBranch": "windows",
            },
        }],
        machines={},
    )

    result = expand_worker_pools(config, pool_groups)

    assert len(result) == 1
    pool = result[0]
    assert pool["pool_id"] == "gecko-1/b-win2022-alpha"
    assert pool["provider_id"] == "azure2"
    assert pool["owner"] == "relops@mozilla.com"
    assert pool["config"]["vm_size"] == "Standard_D96ads_v5"
    assert pool["config"]["locations"] == ["central-india"]
    assert pool["config"]["spot"] is True
    assert pool["config"]["image"] == "ronin_b1_windows2022_64_2009_alpha"
    assert pool["config"]["armDeployment"] == {"templateSpecId": "some-template-id"}
    assert pool["config"]["tags"]["sourceBranch"] == "windows"


# ── Test 7: Suffix expansion ──

def test_suffix_expansion():
    """Suffixes expand into separate pools with the suffix in the name."""
    pool_groups = _make_pool_groups()
    config = _minimal_config(
        pools=[{
            "pool_id": "b-linux-docker{suffix}-amd",
            "description": "Worker",
            "provider_id": "fxci-level1-gcp",
            "suffixes": {
                "": {
                    "groups": ["gecko-1"],
                    "machine": "small-machine",
                },
                "-large": {
                    "groups": ["gecko-1"],
                    "machine": "large-machine",
                },
            },
            "maxCapacity": 100,
        }],
        machines={
            "small-machine": {
                "machine_type": "c3d-standard-16",
                "disks": [{"type": "boot", "size_gb": 60}],
            },
            "large-machine": {
                "machine_type": "c3d-standard-30",
                "disks": [{"type": "boot", "size_gb": 60}],
            },
        },
    )

    result = expand_worker_pools(config, pool_groups)

    pool_ids = [p["pool_id"] for p in result]
    assert "gecko-1/b-linux-docker-amd" in pool_ids
    assert "gecko-1/b-linux-docker-large-amd" in pool_ids
    assert len(result) == 2

    # Verify different machines were used
    by_pool = {p["pool_id"]: p for p in result}
    small = by_pool["gecko-1/b-linux-docker-amd"]
    large = by_pool["gecko-1/b-linux-docker-large-amd"]
    assert small["config"]["instance_types"][0]["machine_type"] == "c3d-standard-16"
    assert large["config"]["instance_types"][0]["machine_type"] == "c3d-standard-30"


# ── Test 8: Output structure matches ciadmin format ──

def test_output_structure():
    """Each expanded pool has the required ciadmin WorkerPool fields."""
    pool_groups = _make_pool_groups()
    config = _minimal_config(
        pools=[{
            "pool_id": "b-linux",
            "description": "Test",
            "groups": ["gecko-1"],
            "provider_id": "fxci-level1-gcp",
            "machine": "test-machine",
            "maxCapacity": 10,
        }],
        machines={
            "test-machine": {
                "machine_type": "n2-standard-4",
                "disks": [{"type": "boot", "size_gb": 75}],
            }
        },
    )

    result = expand_worker_pools(config, pool_groups)
    pool = result[0]

    assert "pool_id" in pool
    assert "description" in pool
    assert "owner" in pool
    assert "email_on_error" in pool
    assert "provider_id" in pool
    assert "config" in pool
    assert pool["attributes"] == {}
    assert pool["variants"] == [{}]
    assert pool["template"] is None


# ── Test 9: by-cot resolution for templates ──

def test_by_cot_resolves_provider_id():
    """by-cot resolves to trusted provider for level-3 (cot=True) pools."""
    pool_groups = _make_pool_groups()
    config = _minimal_config(
        pools=[{
            "pool_id": "b-linux",
            "description": "Worker",
            "groups": ["gecko-1", "gecko-3"],
            "provider_id": {
                "by-cot": {
                    "trusted": "fxci-level3-gcp",
                    "default": "fxci-level1-gcp",
                }
            },
            "machine": "test-machine",
            "maxCapacity": 100,
        }],
        machines={
            "test-machine": {
                "machine_type": "n2-standard-4",
                "disks": [{"type": "boot", "size_gb": 75}],
            }
        },
    )

    result = expand_worker_pools(config, pool_groups)

    by_pool = {p["pool_id"]: p for p in result}
    assert by_pool["gecko-1/b-linux"]["provider_id"] == "fxci-level1-gcp"
    assert by_pool["gecko-3/b-linux"]["provider_id"] == "fxci-level3-gcp"


# ── Test 10: Standalone pool (no groups) ──

def test_standalone_pool():
    """Pool with full pool_id and no groups (e.g., infra/build-decision)."""
    pool_groups = _make_pool_groups()
    config = _minimal_config(
        pools=[{
            "pool_id": "infra/build-decision",
            "description": "Build decision worker",
            "provider_id": "fxci-level1-gcp",
            "image": "monopacker-docker-worker-current",
            "machine": "test-machine",
            "maxCapacity": 4,
            "minCapacity": 1,
        }],
        machines={
            "test-machine": {
                "machine_type": "n2-standard-2",
                "disks": [{"type": "boot", "size_gb": 75}],
            }
        },
    )

    result = expand_worker_pools(config, pool_groups)

    assert len(result) == 1
    pool = result[0]
    assert pool["pool_id"] == "infra/build-decision"
    assert pool["provider_id"] == "fxci-level1-gcp"


# ── Test 11: deep_merge utility ──

def test_deep_merge():
    """_deep_merge correctly merges nested dicts."""
    base = {"a": 1, "b": {"c": 2, "d": 3}}
    override = {"b": {"c": 99, "e": 4}, "f": 5}
    result = _deep_merge(base, override)
    assert result == {"a": 1, "b": {"c": 99, "d": 3, "e": 4}, "f": 5}


# ── Test 12: Defaults applied ──

def test_defaults_applied():
    """Default owner and email_on_error from defaults section."""
    pool_groups = _make_pool_groups()
    config = _minimal_config(
        pools=[{
            "pool_id": "b-linux",
            "description": "Worker",
            "groups": ["gecko-1"],
            "provider_id": "fxci-level1-gcp",
            "machine": "test-machine",
            "maxCapacity": 10,
        }],
        machines={
            "test-machine": {
                "machine_type": "n2-standard-4",
                "disks": [{"type": "boot", "size_gb": 75}],
            }
        },
    )

    result = expand_worker_pools(config, pool_groups)

    assert result[0]["owner"] == "test@example.com"
    assert result[0]["email_on_error"] is True


# ── Test 13: Placeholder substitution ──

def test_placeholder_substitution():
    """Placeholders like {pool-group} in config values are substituted."""
    pool_groups = _make_pool_groups()
    config = _minimal_config(
        pools=[{
            "pool_id": "bot",
            "description": "Worker for the {pool-group} bot.",
            "groups": ["code-review"],
            "provider_id": "fxci-level1-gcp",
            "machine": "test-machine",
            "maxCapacity": 100,
        }],
        machines={
            "test-machine": {
                "machine_type": "c2-standard-4",
                "disks": [{"type": "boot", "size_gb": 75}],
            }
        },
    )

    result = expand_worker_pools(config, pool_groups)

    assert len(result) == 1
    assert result[0]["pool_id"] == "code-review/bot"
    assert result[0]["description"] == "Worker for the code-review bot."


# ── Test 14: Integration with real compressed YAML ──

def test_integration_expand_all_pools():
    """Expand the real worker-pools.yml and verify pool count."""
    import yaml
    with open("worker-pools.yml") as f:
        config = yaml.safe_load(f)
    with open("pool-groups.yml") as f:
        pg_config = yaml.safe_load(f)

    pool_groups = load_pool_groups(pg_config)
    result = expand_worker_pools(config, pool_groups)

    # Should produce a large number of pools (hundreds)
    assert len(result) > 100

    # Every pool should have required fields
    for pool in result:
        assert "pool_id" in pool
        assert "/" in pool["pool_id"], f"pool_id missing '/': {pool['pool_id']}"
        assert "description" in pool
        assert "owner" in pool
        assert "provider_id" in pool
        assert pool["attributes"] == {}
        assert pool["variants"] == [{}]
        assert pool["template"] is None

    # Spot check some known pools
    pool_ids = {p["pool_id"] for p in result}
    assert "gecko-1/b-linux" in pool_ids or "gecko-1/b-linux" in pool_ids
    assert "infra/build-decision" in pool_ids


# ── Test 15: Suffix with by-suffix in maxCapacity ──

def test_by_suffix_resolution():
    """by-suffix values resolve based on the current suffix."""
    pool_groups = _make_pool_groups()
    config = _minimal_config(
        pools=[{
            "pool_id": "t-linux-xlarge{suffix}-gcp",
            "description": "Worker",
            "provider_id": "fxci-level1-gcp",
            "machine": "test-machine",
            "suffixes": {
                "": {"groups": ["gecko-t"]},
                "-source": {"groups": ["gecko-t"]},
            },
            "maxCapacity": {
                "by-trust-domain": {
                    "gecko": {
                        "by-suffix": {
                            "": 2500,
                            "-source": 200,
                        }
                    },
                    "default": 100,
                }
            },
        }],
        machines={
            "test-machine": {
                "machine_type": "n2-standard-4",
                "disks": [{"type": "boot", "size_gb": 75}],
            }
        },
    )

    result = expand_worker_pools(config, pool_groups)

    by_pool = {p["pool_id"]: p for p in result}
    assert by_pool["gecko-t/t-linux-xlarge-gcp"]["config"]["maxCapacity"] == 2500
    assert by_pool["gecko-t/t-linux-xlarge-source-gcp"]["config"]["maxCapacity"] == 200
