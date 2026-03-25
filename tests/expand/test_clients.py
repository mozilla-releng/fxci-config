"""Tests for expand/clients.py."""

import json
import os
import yaml
import pytest

from expand.clients import expand_clients, expand_clients_from_file

BASELINE_PATH = "baseline/resources.json"
_baseline_missing = not os.path.exists(BASELINE_PATH)


# --- Minimal configs for unit tests ---

MINIMAL_AUTOPHONE = {
    "autophone-clients": {
        "bitbar": {
            "base-scopes": [
                "auth:sentry:tc-worker-script",
                "auth:statsum:tc-worker-script",
                "auth:webhooktunnel",
                "auth:websocktunnel-token:firefoxcitc/bitbar.*",
            ],
            "worker-id-prefix": "bitbar",
            "devices": [
                {"name": "gecko-t-bitbar-perf-p6", "queue": "gecko-t-bitbar-gw-perf-p6"},
                {
                    "name": "bitbar-x-test-1",
                    "queue": "gecko-t-bitbar-gw-test-1",
                    "description": "Test device",
                },
            ],
        },
    },
}

MINIMAL_K8S = {
    "scriptworker-k8s-clients": {
        "addon": {
            "dev": ["gecko-1"],
            "prod": ["gecko-1", "gecko-3"],
        },
        "beetmover": {
            "dev": [
                {
                    "pool-group": "xpi-1",
                    "description": "xpi level 1 nonprod beetmover scriptworker",
                    "extra-scopes": ["queue:get-artifact:xpi/*"],
                },
            ],
        },
    },
}

MINIMAL_EXPLICIT = {
    "scriptworker-explicit-clients": {
        "project/releng/scriptworker/v2/iscript/prod": {
            "description": "",
            "scopes": [
                "assume:worker-type:scriptworker-prov-v1/signing-mac-v1",
                "queue:get-artifact:releng/partner/*",
                "queue:get-artifact:private/openh264/*",
                "queue:worker-id:signing-mac-v1/mac-v3-signing*",
            ],
        },
    },
}

MINIMAL_GW = {
    "generic-worker-clients": {
        "snakepit-2080ti": {
            "description": "snakepit 2080ti workers",
            "scopes": [
                "assume:worker-type:translations-1/*",
                "queue:worker-id:snakepit/mlc*",
            ],
        },
    },
}

MINIMAL_V3_MAC = {
    "v3-mac-signing-clients": {
        "gecko-3": {
            "description": "Production signing for Firefox on macOS 14 (M2).",
            "extra-scopes": ["queue:get-artifact:private/openh264/*"],
        },
        "gecko-t": {
            "description": "Dep signing for Firefox on macOS 14 (M2).",
        },
        "comm-3": {
            "description": "Production signing for Thunderbird.",
        },
    },
}

MINIMAL_ONEOFF = {
    "clients": {
        "project/releng/fxci-config/apply": {
            "description": "Used to run `tc-admin apply` in mozilla-releng/fxci-config.",
            "scopes": ["*"],
        },
    },
}

DESC_PREFIX = "*DO NOT EDIT* - This resource is configured automatically.\n\n"


class TestExpandAutophone:
    def test_bitbar_device_count(self):
        result = expand_clients(MINIMAL_AUTOPHONE)
        assert len(result) == 2

    def test_bitbar_device_scopes(self):
        result = expand_clients(MINIMAL_AUTOPHONE)
        client = result["project/autophone/gecko-t-bitbar-perf-p6"]
        assert "queue:claim-work:proj-autophone/gecko-t-bitbar-gw-perf-p6" in client["scopes"]
        assert "queue:worker-id:bitbar/*" in client["scopes"]
        assert "auth:sentry:tc-worker-script" in client["scopes"]
        assert len(client["scopes"]) == 6

    def test_bitbar_device_with_description(self):
        result = expand_clients(MINIMAL_AUTOPHONE)
        client = result["project/autophone/bitbar-x-test-1"]
        assert client["description"] == DESC_PREFIX + "Test device"

    def test_bitbar_device_without_description(self):
        result = expand_clients(MINIMAL_AUTOPHONE)
        client = result["project/autophone/gecko-t-bitbar-perf-p6"]
        assert client["description"] == DESC_PREFIX

    def test_scopes_are_sorted(self):
        result = expand_clients(MINIMAL_AUTOPHONE)
        for client in result.values():
            assert client["scopes"] == sorted(client["scopes"])


class TestExpandScriptworkerK8s:
    def test_addon_client_count(self):
        result = expand_clients(MINIMAL_K8S)
        addon_clients = [k for k in result if "/addon/" in k]
        assert len(addon_clients) == 3  # dev/gecko-1, prod/gecko-1, prod/gecko-3

    def test_addon_dev_scopes(self):
        result = expand_clients(MINIMAL_K8S)
        client = result["project/releng/scriptworker/v2/addon/dev/firefoxci-gecko-1"]
        assert sorted(client["scopes"]) == [
            "queue:claim-work:scriptworker-k8s/gecko-1-addon-dev",
            "queue:worker-id:gecko-1-addon-dev/gecko-1-addon-dev-*",
        ]

    def test_addon_prod_scopes(self):
        result = expand_clients(MINIMAL_K8S)
        client = result["project/releng/scriptworker/v2/addon/prod/firefoxci-gecko-3"]
        assert sorted(client["scopes"]) == [
            "queue:claim-work:scriptworker-k8s/gecko-3-addon",
            "queue:worker-id:gecko-3-addon/gecko-3-addon-*",
        ]

    def test_extra_scopes(self):
        result = expand_clients(MINIMAL_K8S)
        client = result["project/releng/scriptworker/v2/beetmover/dev/firefoxci-xpi-1"]
        assert "queue:get-artifact:xpi/*" in client["scopes"]
        assert "queue:claim-work:scriptworker-k8s/xpi-1-beetmover-dev" in client["scopes"]

    def test_description_from_entry(self):
        result = expand_clients(MINIMAL_K8S)
        client = result["project/releng/scriptworker/v2/beetmover/dev/firefoxci-xpi-1"]
        assert client["description"] == DESC_PREFIX + "xpi level 1 nonprod beetmover scriptworker"

    def test_empty_description(self):
        result = expand_clients(MINIMAL_K8S)
        client = result["project/releng/scriptworker/v2/addon/dev/firefoxci-gecko-1"]
        assert client["description"] == DESC_PREFIX


class TestExpandScriptworkerExplicit:
    def test_explicit_client(self):
        result = expand_clients(MINIMAL_EXPLICIT)
        client = result["project/releng/scriptworker/v2/iscript/prod"]
        assert "assume:worker-type:scriptworker-prov-v1/signing-mac-v1" in client["scopes"]
        assert len(client["scopes"]) == 4

    def test_explicit_description(self):
        result = expand_clients(MINIMAL_EXPLICIT)
        client = result["project/releng/scriptworker/v2/iscript/prod"]
        assert client["description"] == DESC_PREFIX


class TestExpandGenericWorker:
    def test_generic_worker(self):
        result = expand_clients(MINIMAL_GW)
        client = result["project/releng/generic-worker/snakepit-2080ti"]
        assert client["description"] == DESC_PREFIX + "snakepit 2080ti workers"
        assert len(client["scopes"]) == 2


class TestExpandOneOff:
    def test_oneoff_client(self):
        result = expand_clients(MINIMAL_ONEOFF)
        client = result["project/releng/fxci-config/apply"]
        assert client["scopes"] == ["*"]
        assert "tc-admin apply" in client["description"]


class TestExpandV3MacSigning:
    def test_prod_client(self):
        result = expand_clients(MINIMAL_V3_MAC)
        client = result["project/releng/scriptworker/v3/mac-signing/prod/firefoxci-gecko-3"]
        assert "assume:worker-type:scriptworker-prov-v1/gecko-signing-mac14m2" in client["scopes"]
        assert "queue:worker-id:gecko-signing-mac14m2/gecko-signing-mac14m2*" in client["scopes"]
        assert "queue:get-artifact:private/openh264/*" in client["scopes"]
        assert len(client["scopes"]) == 3

    def test_dep_client(self):
        result = expand_clients(MINIMAL_V3_MAC)
        client = result["project/releng/scriptworker/v3/mac-signing/prod/firefoxci-gecko-t"]
        assert "assume:worker-type:scriptworker-prov-v1/dep-gecko-signing-mac14m2" in client["scopes"]
        assert "queue:worker-id:dep-gecko-signing-mac14m2/dep-gecko-signing-mac14m2*" in client["scopes"]
        assert len(client["scopes"]) == 2

    def test_client_count(self):
        result = expand_clients(MINIMAL_V3_MAC)
        assert len(result) == 3

    def test_description(self):
        result = expand_clients(MINIMAL_V3_MAC)
        client = result["project/releng/scriptworker/v3/mac-signing/prod/firefoxci-comm-3"]
        assert client["description"] == DESC_PREFIX + "Production signing for Thunderbird."
        assert "assume:worker-type:scriptworker-prov-v1/comm-signing-mac14m2" in client["scopes"]


class TestExpandCombined:
    def test_all_sections(self):
        config = {}
        config.update(MINIMAL_AUTOPHONE)
        config.update(MINIMAL_K8S)
        config.update(MINIMAL_EXPLICIT)
        config.update(MINIMAL_GW)
        config.update(MINIMAL_V3_MAC)
        config.update(MINIMAL_ONEOFF)
        result = expand_clients(config)
        # 2 autophone + 3 addon + 1 beetmover + 1 explicit + 1 gw + 3 v3-mac + 1 oneoff = 12
        assert len(result) == 12

    def test_empty_config(self):
        result = expand_clients({})
        assert result == {}


class TestExpandFromFile:
    def test_expand_from_file_count(self):
        """Expand from the real compressed YAML and check count."""
        result = expand_clients_from_file("clients.yml")
        assert len(result) == 249

    @pytest.mark.skipif(_baseline_missing, reason="baseline/resources.json not present")
    def test_expand_from_file_matches_baseline(self):
        """Verify all 249 clients match the baseline exactly."""
        result = expand_clients_from_file("clients.yml")
        with open(BASELINE_PATH) as f:
            data = json.load(f)

        baseline = {}
        for r in data.get("resources", []):
            if r.get("kind") == "Client":
                baseline[r["clientId"]] = {
                    "description": r.get("description", ""),
                    "scopes": sorted(r.get("scopes", [])),
                }

        assert set(result.keys()) == set(baseline.keys()), (
            f"Client ID mismatch: "
            f"missing={sorted(baseline.keys() - result.keys())}, "
            f"extra={sorted(result.keys() - baseline.keys())}"
        )

        for cid in sorted(result.keys()):
            assert result[cid]["scopes"] == baseline[cid]["scopes"], (
                f"Scope mismatch for {cid}: "
                f"got {result[cid]['scopes']}, "
                f"expected {baseline[cid]['scopes']}"
            )
            assert result[cid]["description"] == baseline[cid]["description"], (
                f"Description mismatch for {cid}: "
                f"got {repr(result[cid]['description'][:60])}, "
                f"expected {repr(baseline[cid]['description'][:60])}"
            )
