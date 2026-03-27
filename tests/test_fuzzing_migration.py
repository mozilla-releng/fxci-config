#!/usr/bin/env python3
"""
Validate that fxci-config generates all fuzzing entities that were
previously in community-tc-config, plus all its original entities.

Usage:
    python tests/test_fuzzing_migration.py \
        --community-tc-json /tmp/community-tc-all.json \
        --fxci-before-json /tmp/fxci-all-before.json \
        --fxci-after-json /tmp/fxci-all-after.json
"""

import argparse
import json
import sys

# Resources that exist in community-tc but are expected to NOT exist in fxci
# because of architectural differences between the two repos.
EXPECTED_GAPS = {
    # community-tc creates worker-pool roles; fxci does not
    "Role=worker-pool:proj-fuzzing/bugmon-monitor",
    "Role=worker-pool:proj-fuzzing/bugmon-pernosco",
    "Role=worker-pool:proj-fuzzing/bugmon-pernosco-staging",
    "Role=worker-pool:proj-fuzzing/bugmon-processor",
    "Role=worker-pool:proj-fuzzing/bugmon-processor-windows",
    "Role=worker-pool:proj-fuzzing/ci",
    "Role=worker-pool:proj-fuzzing/ci-arm64",
    "Role=worker-pool:proj-fuzzing/ci-windows",
    "Role=worker-pool:proj-fuzzing/decision",
    "Role=worker-pool:proj-fuzzing/grizzly-reduce-worker",
    "Role=worker-pool:proj-fuzzing/grizzly-reduce-worker-android",
    "Role=worker-pool:proj-fuzzing/grizzly-reduce-worker-windows",
    "Role=worker-pool:proj-fuzzing/grizzly-reduce-worker-windows-ngpu",
    "Role=worker-pool:proj-fuzzing/nss-corpus-update-worker",
    # community-tc creates docker-worker secrets; fxci does not
    "Secret=worker-pool:proj-fuzzing/bugmon-pernosco",
    # externally managed hook not defined in fuzzing.yml
    "Role=hook-id:project-fuzzing/failed-log-ingestor",
}


def resource_id(r):
    """Extract the canonical ID from a resource dict."""
    kind = r["kind"]
    if kind == "WorkerPool":
        return f"WorkerPool={r['workerPoolId']}"
    elif kind == "Hook":
        return f"Hook={r.get('hookGroupId', '')}/{r['hookId']}"
    elif kind == "Role":
        return f"Role={r['roleId']}"
    elif kind == "Client":
        return f"Client={r['clientId']}"
    elif kind == "Secret":
        return f"Secret={r['name']}"
    return f"{kind}=?"


def is_fuzzing_resource(r):
    """Check if a resource is fuzzing-related, by resource ID only."""
    rid = resource_id(r)
    return "fuzzing" in rid.lower()


def main():
    parser = argparse.ArgumentParser(
        description="Validate fuzzing migration from community-tc to fxci"
    )
    parser.add_argument("--community-tc-json", required=True)
    parser.add_argument("--fxci-before-json", required=True)
    parser.add_argument("--fxci-after-json", required=True)
    args = parser.parse_args()

    community = json.load(open(args.community_tc_json))
    fxci_before = json.load(open(args.fxci_before_json))
    fxci_after = json.load(open(args.fxci_after_json))

    community_fuzzing = [r for r in community["resources"] if is_fuzzing_resource(r)]
    fxci_before_ids = {resource_id(r) for r in fxci_before["resources"]}
    fxci_after_ids = {resource_id(r) for r in fxci_after["resources"]}

    errors = []

    # Check 1: All fuzzing resources from community-tc exist in fxci-after
    # (minus expected gaps)
    print(
        f"\n=== Check 1: Fuzzing resources migrated ({len(community_fuzzing)} total) ==="
    )
    for r in sorted(community_fuzzing, key=lambda r: resource_id(r)):
        rid = resource_id(r)
        if rid in fxci_after_ids:
            print(f"  OK:   {rid}")
        elif rid in EXPECTED_GAPS:
            print(f"  SKIP: {rid} (expected gap)")
        else:
            errors.append(f"MISSING in fxci: {rid}")
            print(f"  FAIL: {rid}")

    # Check 2: No regressions - all fxci-before resources still in fxci-after
    print(f"\n=== Check 2: No regressions ({len(fxci_before_ids)} pre-existing) ===")
    missing_before = fxci_before_ids - fxci_after_ids
    if missing_before:
        for rid in sorted(missing_before):
            errors.append(f"REGRESSION: {rid} was in fxci-before but not fxci-after")
            print(f"  FAIL: {rid}")
    else:
        print(f"  OK: All {len(fxci_before_ids)} pre-existing resources preserved")

    # Check 3: fxci-after has MORE resources than fxci-before
    print("\n=== Check 3: Resource count increased ===")
    print(f"  fxci-before: {len(fxci_before_ids)}")
    print(f"  fxci-after:  {len(fxci_after_ids)}")
    new_resources = fxci_after_ids - fxci_before_ids
    print(f"  New resources: {len(new_resources)}")

    # Summary
    print("\n=== Summary ===")
    if errors:
        print(f"FAILED: {len(errors)} errors")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print("PASSED: All fuzzing resources migrated, no regressions")
        sys.exit(0)


if __name__ == "__main__":
    main()
