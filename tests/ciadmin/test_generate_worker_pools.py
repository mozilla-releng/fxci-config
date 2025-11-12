# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from argparse import Namespace

import pytest
from tcadmin.resources import Resources
from tcadmin.resources.worker_pool import WorkerPool as TCWorkerPool

from ciadmin.generate.ciconfig.environment import Environment
from ciadmin.generate.ciconfig.worker_images import WorkerImage, WorkerImages
from ciadmin.generate.ciconfig.worker_pools import WorkerPool
from ciadmin.generate.worker_pools import (
    is_invalid_gcp_instance_type,
    make_worker_pool,
)
from ciadmin.util.templates import merge


@pytest.fixture
def environment():
    return Environment(
        name="cluster",
        root_url="https://tc.example.com",
        modify_resources=[],
        worker_manager={
            "providers": {
                "aws": {
                    "implementation": "aws",
                },
                "google": {
                    "implementation": "google",
                },
                "azure": {
                    "implementation": "azure",
                },
            },
        },
        aws_config={
            "availability-zones": ["us-east1a"],
            "invalid-instances": [],
            "security-groups": ["sg"],
            "subnet-id": "subnet",
        },
        google_config={"zones": ["us-east1a"]},
        azure_config={"untrusted_subscription": "subscription_id"},
    )


@pytest.fixture
def make_pool():
    def inner(provider, extra_config=None):
        config = {
            "image": "image-1",
            "maxCapacity": 10,
        }

        if provider == "aws":
            config.update(
                {
                    "instance_types": [{"instanceType": "c5.large"}],
                    "regions": ["us-east1"],
                }
            )
        elif provider == "google":
            config.update(
                {
                    "instance_types": [{"disks": [], "machine_type": "n2-custom"}],
                    "regions": ["us-east1"],
                }
            )
        elif provider == "azure":
            config.update(
                {
                    "locations": ["us-east1"],
                    "image_resource_group": "rg",
                    "vmSizes": [{"vmSize": "Standard_F8s_v2"}],
                    "worker-config": {"genericWorker": {"config": {}}},
                    "worker-purpose": "test",
                }
            )

        if extra_config:
            config = merge(config, extra_config)

        return WorkerPool(
            pool_id="provId/my-worker-pool",
            description="a test workerpool",
            owner="user@example.com",
            provider_id=provider,
            config=config,
            email_on_error=False,
        )

    return inner


@pytest.fixture
def make_images():
    def inner(extra_config=None):
        cloud_config = {
            "google": {},
            "aws": {"us-east1": "id"},
            "azure": {
                "deployment_id": "d_id",
                "us-east1": "ue1_id",
                "version": "ver_id",
                "resource_group": "rgroup_id",
                "name": "name_id",
            },
        }
        if extra_config:
            cloud_config = merge(cloud_config, extra_config)

        return WorkerImages(
            [
                WorkerImage(
                    "image-1",
                    clouds=cloud_config,
                ),
            ]
        )

    return inner


def assert_common(pool):
    config = pool.config
    assert config["minCapacity"] == 0
    assert config["maxCapacity"] == 10
    assert config["scalingRatio"] == 1
    assert len(config["launchConfigs"]) > 0


def assert_aws_basic(pool):
    assert_common(pool)
    config = pool.config
    assert config["launchConfigs"][0] == {
        "additionalUserData": {},
        "launchConfig": {
            "ImageId": "id",
            "InstanceMarketOptions": {"MarketType": "spot"},
            "InstanceType": "c5.large",
            "Placement": {"AvailabilityZone": "us-east1a"},
            "SecurityGroupIds": ["sg"],
            "SubnetId": "subnet",
        },
        "region": "us-east1",
        "workerConfig": {"capacity": 1},
        "workerManager": {
            "capacityPerInstance": 1,
            "launchConfigId": "lc-abb9d2d6cbe96a47eecb",
        },
    }


def assert_google_basic(pool):
    assert_common(pool)

    config = pool.config
    assert config["launchConfigs"][0] == {
        "disks": [],
        "machineType": "zones/us-east1a/machineTypes/n2-custom",
        "networkInterfaces": [{"accessConfigs": [{"type": "ONE_TO_ONE_NAT"}]}],
        "region": "us-east1",
        "scheduling": {
            "instanceTerminationAction": "DELETE",
            "provisioningModel": "SPOT",
            "onHostMaintenance": "terminate",
        },
        "workerConfig": {"capacity": 1},
        "workerManager": {
            "capacityPerInstance": 1,
            "launchConfigId": "lc-fbffa60a697114fb4175",
        },
        "zone": "us-east1a",
    }


def assert_azure_basic(pool):
    assert_common(pool)

    config = pool.config
    assert config["launchConfigs"][0] == {
        "billingProfile": {"maxPrice": -1},
        "evictionPolicy": "Delete",
        "hardwareProfile": {"vmSize": {"vmSize": "Standard_F8s_v2"}},
        "location": "useast1",
        "priority": "spot",
        "storageProfile": {
            "imageReference": {
                "id": "/subscriptions/subscription_id/resourceGroups/rgroup_id/providers/Microsoft.Compute/images/ue1_id-d_id"  # noqa: E501
            }
        },
        "subnetId": "/subscriptions/subscription_id/resourceGroups/rg-us-east1-test/providers/Microsoft.Network/virtualNetworks/vn-us-east1-test/subnets/sn-us-east1-test",  # noqa: E501
        "tags": {"deploymentId": "d_id"},
        "workerConfig": {"genericWorker": {"config": {}}},
        "workerManager": {
            "capacityPerInstance": 1,
            "launchConfigId": "lc-1e93272fb618ed461059",
        },
    }


def assert_azure_version(pool):
    assert_common(pool)

    config = pool.config
    assert config["launchConfigs"][0] == {
        "billingProfile": {"maxPrice": -1},
        "evictionPolicy": "Delete",
        "hardwareProfile": {"vmSize": {"vmSize": "Standard_F8s_v2"}},
        "location": "useast1",
        "priority": "spot",
        "storageProfile": {
            "imageReference": {
                "id": "/subscriptions/subscription_id/resourceGroups/rgroup_id/providers/Microsoft.Compute/galleries/name_id/images/name_id/versions/ver_id"  # noqa: E501
            }
        },
        "subnetId": "/subscriptions/subscription_id/resourceGroups/rg-us-east1-test/providers/Microsoft.Network/virtualNetworks/vn-us-east1-test/subnets/sn-us-east1-test",  # noqa: E501
        "tags": {"deploymentId": "d_id"},
        "workerConfig": {"genericWorker": {"config": {}}},
        "workerManager": {
            "capacityPerInstance": 1,
            "launchConfigId": "lc-93e8de7d6edec4bfbed4",
        },
    }


def assert_azure_arm(pool):
    assert_common(pool)

    config = pool.config
    launch_config = config["launchConfigs"][0]

    assert launch_config["location"] == "useast1"
    assert launch_config["tags"] == {"deploymentId": "d_id"}
    assert launch_config["workerConfig"] == {"genericWorker": {"config": {}}}

    worker_manager = launch_config["workerManager"]
    assert worker_manager["capacityPerInstance"] == 1
    assert "launchConfigId" in worker_manager

    arm_deployment = launch_config["armDeployment"]
    assert arm_deployment["mode"] == "Incremental"
    assert (
        arm_deployment["templateLink"]["id"]
        == "/subscriptions/subscription_id/resourceGroups/templates/providers/Microsoft.Resources/templateSpecs/fxci-test/versions/42"
    )  # noqa: E501
    parameters = arm_deployment["parameters"]
    assert parameters == {
        "customParam": {"value": "customValue"},
        "imageId": {
            "value": "/subscriptions/subscription_id/resourceGroups/rgroup_id/providers/Microsoft.Compute/galleries/name_id/images/name_id/versions/ver_id"  # noqa: E501
        },
        "location": {"value": "us-east1"},
        "priority": {"value": "Regular"},
        "subnetId": {
            "value": "/subscriptions/subscription_id/resourceGroups/rg-us-east1-test/providers/Microsoft.Network/virtualNetworks/vn-us-east1-test/subnets/sn-us-east1-test"  # noqa: E501
        },
        "vmSize": {"value": "Standard_F8s_v2"},
    }

    assert "hardwareProfile" not in launch_config
    assert "storageProfile" not in launch_config


def assert_azure_arm_disabled(pool):
    assert_common(pool)

    config = pool.config
    launch_config = config["launchConfigs"][0]
    assert "armDeployment" not in launch_config

    normalized_vm = dict(launch_config["hardwareProfile"]["vmSize"])
    assert normalized_vm.pop("armDeployment", None) is False

    normalized_launch_config = {k: v for k, v in launch_config.items()}
    normalized_launch_config["hardwareProfile"] = {"vmSize": normalized_vm}
    normalized_launch_config["workerManager"] = dict(launch_config["workerManager"])

    expected = {
        "billingProfile": {"maxPrice": -1},
        "evictionPolicy": "Delete",
        "hardwareProfile": {"vmSize": {"vmSize": "Standard_F8s_v2"}},
        "location": "useast1",
        "priority": "spot",
        "storageProfile": {
            "imageReference": {
                "id": "/subscriptions/subscription_id/resourceGroups/rgroup_id/providers/Microsoft.Compute/galleries/name_id/images/name_id/versions/ver_id"  # noqa: E501
            }
        },
        "subnetId": "/subscriptions/subscription_id/resourceGroups/rg-us-east1-test/providers/Microsoft.Network/virtualNetworks/vn-us-east1-test/subnets/sn-us-east1-test",  # noqa: E501
        "tags": {"deploymentId": "d_id"},
        "workerConfig": {"genericWorker": {"config": {}}},
        "workerManager": {
            "capacityPerInstance": 1,
            "launchConfigId": normalized_launch_config["workerManager"][
                "launchConfigId"
            ],
        },
    }

    normalized_launch_config["workerManager"]["launchConfigId"] = expected[
        "workerManager"
    ]["launchConfigId"]
    assert normalized_launch_config == expected


def assert_scaling_ratio(pool):
    assert pool.config["scalingRatio"] == 0.5


def assert_guest_accelerators(pool):
    assert pool.config["launchConfigs"][1]["guestAccelerators"][0] == {
        "acceleratorCount": 4,
        "acceleratorType": "zones/us-east1a/acceleratorTypes/nvidia-tesla-v100",
    }


@pytest.mark.parametrize(
    "provider,extra_pool_config,extra_cloud_config",
    (
        pytest.param("aws", None, None, id="aws_basic"),
        pytest.param("google", None, None, id="google_basic"),
        pytest.param(
            "google",
            {
                "instance_types": [
                    {
                        "disks": [],
                        "guestAccelerators": [
                            {
                                "acceleratorCount": 4,
                                "acceleratorType": "nvidia-tesla-v100",
                            }
                        ],
                        "machine_type": "n1-highmem-32",
                    }
                ]
            },
            None,
            id="guest_accelerators",
        ),
        pytest.param("azure", None, {"version": "NA"}, id="azure_basic"),
        pytest.param("azure", None, None, id="azure_version"),
        pytest.param(
            "azure",
            {
                "armDeployment": {
                    "templateSpecId": "/subscriptions/subscription_id/resourceGroups/templates/providers/Microsoft.Resources/templateSpecs/fxci-test/versions/42",  # noqa: E501
                    "parameters": {
                        "customParam": "customValue",
                        "priority": {"value": "Regular"},
                    },
                },
            },
            None,
            id="azure_arm",
        ),
        pytest.param(
            "azure",
            {
                "armDeployment": {
                    "templateSpecId": "/subscriptions/subscription_id/resourceGroups/templates/providers/Microsoft.Resources/templateSpecs/fxci-test/versions/42",  # noqa: E501
                }
            },
            None,
            id="azure_arm_disabled",
        ),
        pytest.param("aws", {"scalingRatio": 0.5}, None, id="scaling_ratio"),
    ),
)
@pytest.mark.asyncio
async def test_make_worker_pool(
    request,
    mocker,
    environment,
    make_pool,
    make_images,
    provider,
    extra_pool_config,
    extra_cloud_config,
):
    m = mocker.patch("tcadmin.appconfig.AppConfig.current")
    m.return_value = Namespace(description_prefix="PREFIX - ")

    pool = make_pool(provider, extra_pool_config)
    if (
        extra_pool_config
        and "vmSizes" not in extra_pool_config
        and request.node.callspec.id == "azure_arm_disabled"
    ):
        pool.config["vmSizes"][0]["armDeployment"] = False
    if extra_cloud_config:
        extra_cloud_config = {provider: extra_cloud_config}
    images = make_images(extra_cloud_config)
    result = await make_worker_pool(environment, Resources(), pool, images, {})
    print(result)
    assert result.workerPoolId == "provId/my-worker-pool"
    assert isinstance(result, TCWorkerPool)
    assert result.description == "PREFIX - a test workerpool"
    assert result.owner == "user@example.com"

    # Assertion callbacks correspond to `id` of parametrized test.
    param_id = request.node.callspec.id
    globals()[f"assert_{param_id}"](result)


@pytest.mark.parametrize(
    "invalid_instances,zone,machine_type,expected",
    [
        # Basic family matching - should match when zone and family match
        (
            [{"zones": ["us-west1-a"], "families": ["n2"]}],
            "us-west1-a",
            "n2-standard-2",
            True,
        ),
        # Basic family matching - should not match when family differs
        (
            [{"zones": ["us-west1-a"], "families": ["n2"]}],
            "us-west1-a",
            "c4d-standard-2",
            False,
        ),
        # Multiple families - should match first family
        (
            [{"zones": ["us-west1-a"], "families": ["n2", "c4d"]}],
            "us-west1-a",
            "n2-standard-2",
            True,
        ),
        # Multiple families - should match second family
        (
            [{"zones": ["us-west1-a"], "families": ["n2", "c4d"]}],
            "us-west1-a",
            "c4d-standard-2",
            True,
        ),
        # Multiple families - should not match unlisted family
        (
            [{"zones": ["us-west1-a"], "families": ["c4d", "c2"]}],
            "us-west1-a",
            "n2-standard-2",
            False,
        ),
        # Suffix filtering - should match when suffix matches
        (
            [
                {
                    "zones": ["us-west1-a"],
                    "families": ["n2"],
                    "suffixes": ["lssd", "ext"],
                }
            ],
            "us-west1-a",
            "n2-standard-8-lssd",
            True,
        ),
        # Suffix filtering - should not match when suffix differs
        (
            [{"zones": ["us-west1-a"], "families": ["n2"], "suffixes": ["lssd"]}],
            "us-west1-a",
            "n2-standard-8",
            False,
        ),
        # No suffix filter - matches all variants (without suffix)
        (
            [{"zones": ["us-west1-a"], "families": ["n2"]}],
            "us-west1-a",
            "n2-standard-16",
            True,
        ),
        # No suffix filter - matches all variants (with any suffix)
        (
            [{"zones": ["us-west1-a"], "families": ["n2"]}],
            "us-west1-a",
            "n2-standard-16-ext",
            True,
        ),
        # No suffix filter (empty list) - matches all variants (with any suffix)
        (
            [{"zones": ["us-west1-a"], "families": ["n2"], "suffixes": []}],
            "us-west1-a",
            "n2-standard-16-ext",
            True,
        ),
        # No suffix filter - strictly no suffix (we don't really have a use case for this "feature" yet)
        (
            [{"zones": ["us-west1-a"], "families": ["n2"], "suffixes": [None]}],
            "us-west1-a",
            "n2-standard-16-ext",
            False,
        ),
        # Zone mismatch - should not match when zone differs
        (
            [{"zones": ["us-west1-a"], "families": ["n2"], "suffixes": ["lssd"]}],
            "us-central1-f",
            "n2-standard-8-lssd",
            False,
        ),
        # Family mismatch - should not match when family differs
        (
            [{"zones": ["us-west1-a"], "families": ["n2"], "suffixes": ["lssd"]}],
            "us-west1-a",
            "c4d-standard-8-lssd",
            False,
        ),
    ],
)
def test_is_invalid_gcp_instance_type(invalid_instances, zone, machine_type, expected):
    assert (
        is_invalid_gcp_instance_type(invalid_instances, zone, machine_type) == expected
    )
