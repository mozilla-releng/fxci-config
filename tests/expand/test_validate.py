"""Tests for validate.py — pool comparison and validation logic."""

import json
import sys
import os
import tempfile
import unittest.mock as mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from validate import (
    compare_fields,
    is_accepted,
    load_accepted_diffs,
    load_baseline_pools,
    DO_NOT_EDIT_PREFIX,
    main,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_expanded_pool(pool_id, description="A pool", owner="test@example.com",
                        email_on_error=True, provider_id="fxci-level1-gcp"):
    """Minimal expanded pool dict (snake_case keys)."""
    return {
        "pool_id": pool_id,
        "description": description,
        "owner": owner,
        "email_on_error": email_on_error,
        "provider_id": provider_id,
        "config": {},
    }


def _make_baseline_pool(worker_pool_id, description="A pool", owner="test@example.com",
                        email_on_error=True, provider_id="fxci-level1-gcp"):
    """Minimal baseline WorkerPool dict (camelCase keys, with DO NOT EDIT prefix)."""
    return {
        "kind": "WorkerPool",
        "workerPoolId": worker_pool_id,
        "description": DO_NOT_EDIT_PREFIX + description,
        "owner": owner,
        "emailOnError": email_on_error,
        "providerId": provider_id,
        "config": {},
    }


def _write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)


# ── load_baseline_pools ───────────────────────────────────────────────────────

def test_load_baseline_pools_returns_worker_pools_only():
    """Only resources with kind=WorkerPool are included."""
    data = {
        "resources": [
            {"kind": "WorkerPool", "workerPoolId": "gecko-1/b-linux", "description": ""},
            {"kind": "Client", "clientId": "some-client"},
            {"kind": "WorkerPool", "workerPoolId": "gecko-3/b-linux", "description": ""},
        ]
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name

    try:
        pools = load_baseline_pools(path)
        assert set(pools.keys()) == {"gecko-1/b-linux", "gecko-3/b-linux"}
        assert "some-client" not in str(pools)
    finally:
        os.unlink(path)


def test_load_baseline_pools_keyed_by_worker_pool_id():
    """Each pool is keyed by its workerPoolId value."""
    data = {
        "resources": [
            {"kind": "WorkerPool", "workerPoolId": "infra/build-decision",
             "owner": "relops@mozilla.com"},
        ]
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name

    try:
        pools = load_baseline_pools(path)
        assert "infra/build-decision" in pools
        assert pools["infra/build-decision"]["owner"] == "relops@mozilla.com"
    finally:
        os.unlink(path)


def test_load_baseline_pools_empty_resources():
    """Empty resources list returns empty dict."""
    data = {"resources": []}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name

    try:
        pools = load_baseline_pools(path)
        assert pools == {}
    finally:
        os.unlink(path)


# ── load_accepted_diffs ───────────────────────────────────────────────────────

def test_load_accepted_diffs_returns_list():
    """Returns the list from the JSON file."""
    accepted = [
        {"pool_id": "gecko-1/b-linux", "field": "owner"},
        {"pool_id": "infra/build-decision", "field": "description"},
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(accepted, f)
        path = f.name

    try:
        result = load_accepted_diffs(path)
        assert result == accepted
    finally:
        os.unlink(path)


def test_load_accepted_diffs_missing_file_returns_empty():
    """Returns empty list when the file does not exist."""
    result = load_accepted_diffs("/tmp/does-not-exist-accepted-diffs-xyz.json")
    assert result == []


# ── compare_fields ────────────────────────────────────────────────────────────

def test_compare_fields_all_match():
    """No diffs when all fields match (baseline has DO NOT EDIT prefix on description)."""
    expanded = _make_expanded_pool("gecko-1/b-linux", description="My pool",
                                   owner="a@b.com", email_on_error=True,
                                   provider_id="fxci-level1-gcp")
    baseline = _make_baseline_pool("gecko-1/b-linux", description="My pool",
                                   owner="a@b.com", email_on_error=True,
                                   provider_id="fxci-level1-gcp")
    diffs = compare_fields(expanded, baseline)
    assert diffs == []


def test_compare_fields_description_mismatch():
    """Reports diff when description differs (after stripping DO NOT EDIT prefix)."""
    expanded = _make_expanded_pool("gecko-1/b-linux", description="New description")
    baseline = _make_baseline_pool("gecko-1/b-linux", description="Old description")
    diffs = compare_fields(expanded, baseline)
    assert len(diffs) == 1
    field, exp_val, base_val = diffs[0]
    assert field == "description"
    assert exp_val == "New description"
    assert base_val == "Old description"


def test_compare_fields_strips_do_not_edit_prefix():
    """DO NOT EDIT prefix in baseline description is stripped before comparison."""
    expanded = _make_expanded_pool("gecko-1/b-linux", description="Bare description")
    baseline = {
        "workerPoolId": "gecko-1/b-linux",
        "description": DO_NOT_EDIT_PREFIX + "Bare description",
        "owner": "test@example.com",
        "emailOnError": True,
        "providerId": "fxci-level1-gcp",
    }
    diffs = compare_fields(expanded, baseline)
    assert diffs == []


def test_compare_fields_owner_mismatch():
    """Reports diff when owner differs."""
    expanded = _make_expanded_pool("gecko-1/b-linux", owner="new@example.com")
    baseline = _make_baseline_pool("gecko-1/b-linux", owner="old@example.com")
    diffs = compare_fields(expanded, baseline)
    field_names = [d[0] for d in diffs]
    assert "owner" in field_names


def test_compare_fields_email_on_error_mismatch():
    """Reports diff when emailOnError differs."""
    expanded = _make_expanded_pool("p/q", email_on_error=False)
    baseline = _make_baseline_pool("p/q", email_on_error=True)
    diffs = compare_fields(expanded, baseline)
    field_names = [d[0] for d in diffs]
    assert "email_on_error" in field_names


def test_compare_fields_provider_id_mismatch():
    """Reports diff when providerId differs."""
    expanded = _make_expanded_pool("p/q", provider_id="fxci-level3-gcp")
    baseline = _make_baseline_pool("p/q", provider_id="fxci-level1-gcp")
    diffs = compare_fields(expanded, baseline)
    field_names = [d[0] for d in diffs]
    assert "provider_id" in field_names


def test_compare_fields_multiple_mismatches():
    """Reports multiple diffs when several fields differ."""
    expanded = _make_expanded_pool("p/q", owner="a@x.com", provider_id="fxci-level3-gcp")
    baseline = _make_baseline_pool("p/q", owner="b@y.com", provider_id="fxci-level1-gcp")
    diffs = compare_fields(expanded, baseline)
    assert len(diffs) == 2
    field_names = {d[0] for d in diffs}
    assert field_names == {"owner", "provider_id"}


def test_compare_fields_baseline_no_do_not_edit_prefix():
    """Description without prefix is compared as-is."""
    expanded = _make_expanded_pool("p/q", description="Same")
    baseline = {
        "workerPoolId": "p/q",
        "description": "Same",   # no prefix
        "owner": "test@example.com",
        "emailOnError": True,
        "providerId": "fxci-level1-gcp",
    }
    diffs = compare_fields(expanded, baseline)
    assert diffs == []


# ── is_accepted ───────────────────────────────────────────────────────────────

def test_is_accepted_exact_match():
    """Returns True when pool_id and field both match an entry."""
    accepted = [
        {"pool_id": "gecko-1/b-linux", "field": "owner"},
    ]
    assert is_accepted("gecko-1/b-linux", "owner", "a", "b", accepted) is True


def test_is_accepted_wrong_pool():
    """Returns False when pool_id doesn't match any entry."""
    accepted = [
        {"pool_id": "gecko-1/b-linux", "field": "owner"},
    ]
    assert is_accepted("gecko-2/b-linux", "owner", "a", "b", accepted) is False


def test_is_accepted_wrong_field():
    """Returns False when field doesn't match."""
    accepted = [
        {"pool_id": "gecko-1/b-linux", "field": "owner"},
    ]
    assert is_accepted("gecko-1/b-linux", "description", "a", "b", accepted) is False


def test_is_accepted_empty_list():
    """Returns False for any diff when accepted list is empty."""
    assert is_accepted("gecko-1/b-linux", "owner", "a", "b", []) is False


def test_is_accepted_multiple_entries():
    """Correctly matches among multiple accepted entries."""
    accepted = [
        {"pool_id": "gecko-1/b-linux", "field": "owner"},
        {"pool_id": "infra/build-decision", "field": "description"},
        {"pool_id": "gecko-3/b-linux", "field": "provider_id"},
    ]
    assert is_accepted("infra/build-decision", "description", "x", "y", accepted) is True
    assert is_accepted("gecko-3/b-linux", "provider_id", "x", "y", accepted) is True
    assert is_accepted("gecko-3/b-linux", "owner", "x", "y", accepted) is False


# ── Pool ID set comparison (via main with synthetic data) ─────────────────────

def _run_main_with_synthetic(expanded_pools, baseline_resources, accepted_diffs=None):
    """
    Run main() with fully synthetic data, injecting it via mocks.

    Returns (exit_code, stdout_text).
    """
    import io
    from contextlib import redirect_stdout

    baseline_data = {"resources": baseline_resources}

    if accepted_diffs is None:
        accepted_diffs = []

    buf = io.StringIO()

    with mock.patch("validate.expand_worker_pools_from_files", return_value=expanded_pools), \
         mock.patch("validate.load_baseline_pools", return_value={
             r["workerPoolId"]: r
             for r in baseline_resources
             if r.get("kind") == "WorkerPool"
         }), \
         mock.patch("validate.load_accepted_diffs", return_value=accepted_diffs), \
         mock.patch("sys.argv", ["validate.py", "/dev/null"]), \
         redirect_stdout(buf):
        rc = main()

    return rc, buf.getvalue()


def test_main_all_match_returns_zero():
    """main() returns 0 when expanded and baseline have identical pools with no diffs."""
    expanded = [_make_expanded_pool("gecko-1/b-linux")]
    baseline = [_make_baseline_pool("gecko-1/b-linux")]
    rc, output = _run_main_with_synthetic(expanded, baseline)
    assert rc == 0
    assert "0 total issues" in output


def test_main_extra_pool_returns_nonzero():
    """main() returns non-zero when expanded has pools not in baseline."""
    expanded = [
        _make_expanded_pool("gecko-1/b-linux"),
        _make_expanded_pool("gecko-1/b-extra"),   # not in baseline
    ]
    baseline = [_make_baseline_pool("gecko-1/b-linux")]
    rc, output = _run_main_with_synthetic(expanded, baseline)
    assert rc != 0
    assert "gecko-1/b-extra" in output
    assert "EXTRA" in output


def test_main_missing_pool_returns_nonzero():
    """main() returns non-zero when baseline has pools not in expanded."""
    expanded = [_make_expanded_pool("gecko-1/b-linux")]
    baseline = [
        _make_baseline_pool("gecko-1/b-linux"),
        _make_baseline_pool("gecko-1/b-missing"),  # not in expanded
    ]
    rc, output = _run_main_with_synthetic(expanded, baseline)
    assert rc != 0
    assert "gecko-1/b-missing" in output
    assert "MISSING" in output


def test_main_field_diff_returns_nonzero():
    """main() returns non-zero when a common pool has a field mismatch."""
    expanded = [_make_expanded_pool("gecko-1/b-linux", owner="new@example.com")]
    baseline = [_make_baseline_pool("gecko-1/b-linux", owner="old@example.com")]
    rc, output = _run_main_with_synthetic(expanded, baseline)
    assert rc != 0
    assert "owner" in output
    assert "new@example.com" in output


def test_main_accepted_diff_suppresses_field_issue():
    """Accepted diffs do not contribute to total issues."""
    expanded = [_make_expanded_pool("gecko-1/b-linux", owner="new@example.com")]
    baseline = [_make_baseline_pool("gecko-1/b-linux", owner="old@example.com")]
    accepted = [{"pool_id": "gecko-1/b-linux", "field": "owner"}]
    rc, output = _run_main_with_synthetic(expanded, baseline, accepted_diffs=accepted)
    assert rc == 0
    assert "0 total issues" in output


def test_main_accepted_diff_only_suppresses_matching_field():
    """An accepted entry for one field does not suppress diffs on other fields."""
    expanded = [_make_expanded_pool("gecko-1/b-linux",
                                    owner="new@example.com",
                                    provider_id="fxci-level3-gcp")]
    baseline = [_make_baseline_pool("gecko-1/b-linux",
                                    owner="old@example.com",
                                    provider_id="fxci-level1-gcp")]
    # Only accept the owner diff, not the provider_id diff
    accepted = [{"pool_id": "gecko-1/b-linux", "field": "owner"}]
    rc, output = _run_main_with_synthetic(expanded, baseline, accepted_diffs=accepted)
    assert rc != 0
    assert "provider_id" in output


def test_main_duplicate_pool_ids_reported():
    """Duplicate pool IDs in expanded are flagged."""
    expanded = [
        _make_expanded_pool("gecko-1/b-linux"),
        _make_expanded_pool("gecko-1/b-linux"),  # duplicate
    ]
    baseline = [_make_baseline_pool("gecko-1/b-linux")]
    rc, output = _run_main_with_synthetic(expanded, baseline)
    assert "DUPLICATE" in output


def test_main_empty_both_returns_zero():
    """main() returns 0 when both expanded and baseline are empty."""
    rc, output = _run_main_with_synthetic([], [])
    assert rc == 0
    assert "0 total issues" in output


def test_main_multiple_pools_all_match():
    """main() returns 0 for multiple perfectly-matching pools."""
    pool_ids = ["gecko-1/b-linux", "gecko-3/b-linux", "infra/build-decision"]
    expanded = [_make_expanded_pool(pid) for pid in pool_ids]
    baseline = [_make_baseline_pool(pid) for pid in pool_ids]
    rc, output = _run_main_with_synthetic(expanded, baseline)
    assert rc == 0
    assert "0 total issues" in output
