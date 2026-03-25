#!/usr/bin/env python3
"""Validate expanded worker pools against the baseline resources.json.

Compares pool_id sets and high-level fields (description, owner,
emailOnError, providerId) between the expanded normalized config
and the baseline. Deep config comparison is skipped because
make_worker_pool() transforms the config before it reaches the baseline.
"""

import argparse
import json
import sys

from expand.worker_pools import expand_worker_pools_from_files


def load_baseline_pools(path):
    """Load WorkerPool resources from the baseline, keyed by workerPoolId."""
    with open(path) as f:
        data = json.load(f)
    pools = {}
    for r in data["resources"]:
        if r.get("kind") == "WorkerPool":
            pools[r["workerPoolId"]] = r
    return pools


def load_accepted_diffs(path="accepted-diffs.json"):
    """Load the list of accepted differences."""
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return []


# Field mapping: expanded snake_case -> baseline camelCase
FIELD_MAP = {
    "description": "description",
    "owner": "owner",
    "email_on_error": "emailOnError",
    "provider_id": "providerId",
}


DO_NOT_EDIT_PREFIX = "*DO NOT EDIT* - This resource is configured automatically.\n\n"


def compare_fields(expanded, baseline):
    """Compare high-level fields between expanded and baseline pool.

    Returns a list of (field, expanded_value, baseline_value) tuples for mismatches.
    """
    diffs = []
    for exp_key, base_key in FIELD_MAP.items():
        exp_val = expanded.get(exp_key)
        base_val = baseline.get(base_key)

        # The baseline description has a DO NOT EDIT prefix added by make_worker_pool()
        if exp_key == "description" and isinstance(base_val, str):
            base_val = base_val.removeprefix(DO_NOT_EDIT_PREFIX)

        if exp_val != base_val:
            diffs.append((exp_key, exp_val, base_val))
    return diffs


def is_accepted(pool_id, field, exp_val, base_val, accepted):
    """Check if a specific diff is in the accepted-diffs list."""
    for entry in accepted:
        if (entry.get("pool_id") == pool_id and
                entry.get("field") == field):
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description="Validate expanded config against baseline")
    parser.add_argument("baseline", help="Path to baseline resources.json")
    args = parser.parse_args()

    # Expand pools from normalized config
    expanded_pools = expand_worker_pools_from_files()
    expanded_by_id = {}
    duplicates = []
    for p in expanded_pools:
        pid = p["pool_id"]
        if pid in expanded_by_id:
            duplicates.append(pid)
        expanded_by_id[pid] = p

    # Load baseline
    baseline_pools = load_baseline_pools(args.baseline)
    accepted = load_accepted_diffs()

    expanded_ids = set(expanded_by_id.keys())
    baseline_ids = set(baseline_pools.keys())

    # Pool ID set comparison
    extra = sorted(expanded_ids - baseline_ids)
    missing = sorted(baseline_ids - expanded_ids)
    common = sorted(expanded_ids & baseline_ids)

    print("=" * 70)
    print(f"POOL ID COMPARISON")
    print(f"  Expanded:  {len(expanded_ids)} pools")
    print(f"  Baseline:  {len(baseline_ids)} pools")
    print(f"  Common:    {len(common)}")
    print(f"  Extra:     {len(extra)} (in expanded but not baseline)")
    print(f"  Missing:   {len(missing)} (in baseline but not expanded)")
    print("=" * 70)

    if duplicates:
        print(f"\nDUPLICATE POOL IDs in expanded ({len(duplicates)}):")
        for pid in sorted(set(duplicates)):
            print(f"  {pid}")

    if extra:
        print(f"\nEXTRA pools ({len(extra)}):")
        for pid in extra:
            print(f"  {pid}")

    if missing:
        print(f"\nMISSING pools ({len(missing)}):")
        for pid in missing:
            print(f"  {pid}")

    # Field comparison for common pools
    field_diffs = {}
    for pid in common:
        diffs = compare_fields(expanded_by_id[pid], baseline_pools[pid])
        unaccepted = [
            (f, ev, bv) for f, ev, bv in diffs
            if not is_accepted(pid, f, ev, bv, accepted)
        ]
        if unaccepted:
            field_diffs[pid] = unaccepted

    print(f"\nFIELD COMPARISON (common pools)")
    print(f"  Pools with field diffs: {len(field_diffs)}")
    if field_diffs:
        # Group by field for summary
        field_counts = {}
        for pid, diffs in field_diffs.items():
            for f, ev, bv in diffs:
                field_counts.setdefault(f, []).append(pid)

        for field, pids in sorted(field_counts.items()):
            print(f"\n  {field} mismatches ({len(pids)}):")
            for pid in pids[:10]:
                diffs = [d for d in field_diffs[pid] if d[0] == field]
                for _, ev, bv in diffs:
                    print(f"    {pid}: expanded={ev!r} baseline={bv!r}")
            if len(pids) > 10:
                print(f"    ... and {len(pids) - 10} more")

    # Summary
    total_issues = len(extra) + len(missing) + len(field_diffs)
    print(f"\n{'=' * 70}")
    print(f"SUMMARY: {total_issues} total issues")
    print(f"  Extra: {len(extra)}, Missing: {len(missing)}, Field diffs: {len(field_diffs)}")
    if duplicates:
        print(f"  Duplicates: {len(set(duplicates))}")
    print(f"{'=' * 70}")

    return 0 if total_issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
