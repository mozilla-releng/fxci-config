# -*- coding: utf-8 -*-

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
from ciadmin.generate.worker_pools import make_worker_pool
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
def images():
    return WorkerImages(
        [
            WorkerImage(
                "image-1",
                clouds={
                    "google": {},
                    "aws": {"us-east1": "id"},
                    "azure": {"deployment_id": "d_id", "us-east1": "ue1_id"},
                },
            ),
        ]
    )


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
        "capacityPerInstance": 1,
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
    }


def assert_google_basic(pool):
    assert_common(pool)

    config = pool.config
    assert config["launchConfigs"][0] == {
        "capacityPerInstance": 1,
        "disks": [],
        "machineType": "zones/us-east1a/machineTypes/n2-custom",
        "region": "us-east1",
        "scheduling": {
            "instanceTerminationAction": "DELETE",
            "provisioningModel": "SPOT",
            "onHostMaintenance": "terminate",
        },
        "workerConfig": {"capacity": 1},
        "zone": "us-east1a",
    }


def assert_azure_basic(pool):
    assert_common(pool)

    config = pool.config
    assert config["launchConfigs"][0] == {
        "billingProfile": {"maxPrice": -1},
        "capacityPerInstance": 1,
        "evictionPolicy": "Delete",
        "hardwareProfile": {"vmSize": {"vmSize": "Standard_F8s_v2"}},
        "location": "useast1",
        "priority": "spot",
        "storageProfile": {
            "imageReference": {
                "id": "/subscriptions/subscription_id/resourceGroups/rg/providers/Microsoft.Compute/images/ue1_id-d_id"  # noqa: E501
            }
        },
        "subnetId": "/subscriptions/subscription_id/resourceGroups/rg-us-east1-test/providers/Microsoft.Network/virtualNetworks/vn-us-east1-test/subnets/sn-us-east1-test",  # noqa: E501
        "tags": {"deploymentId": "d_id"},
        "workerConfig": {},
    }


def assert_scaling_ratio(pool):
    assert pool.config["scalingRatio"] == 0.5


def assert_guest_accelerators(pool):
    assert pool.config["launchConfigs"][1]["guestAccelerators"][0] == {
        "acceleratorCount": 4,
        "acceleratorType": "zones/us-east1a/acceleratorTypes/nvidia-tesla-v100",
    }


@pytest.mark.parametrize(
    "provider,extra_config",
    (
        pytest.param("aws", None, id="aws_basic"),
        pytest.param("google", None, id="google_basic"),
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
            id="guest_accelerators",
        ),
        pytest.param("azure", None, id="azure_basic"),
        pytest.param("aws", {"scalingRatio": 0.5}, id="scaling_ratio"),
    ),
)
@pytest.mark.asyncio
async def test_make_worker_pool(
    request, mocker, environment, make_pool, images, provider, extra_config
):
    m = mocker.patch("tcadmin.appconfig.AppConfig.current")
    m.return_value = Namespace(description_prefix="PREFIX - ")

    pool = make_pool(provider, extra_config)
    result = await make_worker_pool(environment, Resources(), pool, images, {})
    print(result)
    assert result.workerPoolId == "provId/my-worker-pool"
    assert isinstance(result, TCWorkerPool)
    assert result.description == "PREFIX - a test workerpool"
    assert result.owner == "user@example.com"

    # Assertion callbacks correspond to `id` of parametrized test.
    param_id = request.node.callspec.id
    globals()[f"assert_{param_id}"](result)
