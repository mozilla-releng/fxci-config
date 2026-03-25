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
    value = {"by-trust-domain": {"gecko": {"by-level": {3: 500, "default": 1000}}, "default": 100}}
    assert resolve_value(value, gecko_3) == 500
    assert resolve_value(value, comm_1) == 100

def test_resolve_in_dict_recursively(gecko_3):
    value = {"max_capacity": {"by-level": {3: 500, "default": 1000}}, "min_capacity": 0}
    result = resolve_value(value, gecko_3)
    assert result == {"max_capacity": 500, "min_capacity": 0}

def test_missing_key_and_no_default_raises(gecko_3):
    value = {"by-trust-domain": {"comm": 300}}
    with pytest.raises(KeyError):
        resolve_value(value, gecko_3)
