import pytest
from expand.pool_groups import load_pool_groups, PoolGroup


def test_expand_trust_domain_with_levels_and_testing():
    config = {"pool-groups": {"gecko": {"levels": [1, 2, 3], "testing": True}}}
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
    config = {"pool-groups": {"mobile": {"levels": [1, 3]}}}
    result = load_pool_groups(config)
    assert "mobile-1" in result
    assert "mobile-3" in result
    assert "mobile-t" not in result


def test_standalone_pool_group():
    config = {"pool-groups": {"code-coverage": {"levels": ["standalone"]}}}
    result = load_pool_groups(config)
    assert "code-coverage" in result
    assert result["code-coverage"].trust_domain == "code-coverage"
    assert result["code-coverage"].level == "standalone"
    assert result["code-coverage"].cot is False


def test_pool_groups_yml_produces_all_expected_groups():
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
