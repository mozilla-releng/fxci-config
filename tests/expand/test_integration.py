"""Verify expanded output has correct structure and counts."""
import json
import os
import pytest
from ciadmin.generate.ciconfig import get

BASELINE_PATH = "baseline/resources.json"
_baseline_missing = not os.path.exists(BASELINE_PATH)


def test_expanded_worker_pools_have_correct_structure():
    from expand import expand_all
    expand_all()
    wp_data = get._cache["worker-pools.yml"]
    for pool_info in wp_data["pools"]:
        assert "pool_id" in pool_info
        assert "/" in pool_info["pool_id"]
        assert pool_info.get("variants") == [{}]
        assert pool_info.get("template") is None
        assert pool_info.get("attributes") == {}
    get._cache.clear()


def test_expanded_clients_have_correct_structure():
    from expand import expand_all
    expand_all()
    cl_data = get._cache["clients.yml"]
    for client_id, info in cl_data.items():
        assert "scopes" in info
        assert isinstance(info["scopes"], list)
        assert "description" in info
    get._cache.clear()


@pytest.mark.skipif(_baseline_missing, reason="baseline/resources.json not present")
def test_expanded_pool_count_matches_baseline():
    with open(BASELINE_PATH) as f:
        baseline = json.load(f)
    baseline_pool_count = sum(1 for r in baseline["resources"] if r["kind"] == "WorkerPool")

    from expand import expand_all
    expand_all()
    wp_data = get._cache["worker-pools.yml"]
    assert len(wp_data["pools"]) == baseline_pool_count
    get._cache.clear()


@pytest.mark.skipif(_baseline_missing, reason="baseline/resources.json not present")
def test_expanded_client_count_matches_baseline():
    with open(BASELINE_PATH) as f:
        baseline = json.load(f)
    baseline_client_count = sum(1 for r in baseline["resources"] if r["kind"] == "Client")

    from expand import expand_all
    expand_all()
    cl_data = get._cache["clients.yml"]
    assert len(cl_data) == baseline_client_count
    get._cache.clear()
