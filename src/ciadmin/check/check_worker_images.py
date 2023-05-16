# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from ciadmin.generate.ciconfig.environment import Environment
from ciadmin.generate.ciconfig.worker_images import WorkerImage
from ciadmin.generate.ciconfig.worker_pools import WorkerPool as WorkerPoolConfig
from ciadmin.generate.worker_pools import generate_pool_variants


@pytest.mark.asyncio
async def check_worker_images_are_used():
    environment = await Environment.current()
    worker_images = await WorkerImage.fetch_all()
    worker_pools = await WorkerPoolConfig.fetch_all()

    used = set()
    for pool in generate_pool_variants(worker_pools, environment):
        if "image" in pool.config:
            used.add(pool.config["image"])

    for image in worker_images.images.values():
        if image.alias_for is None or image.image_name not in used:
            continue
        used.add(image.alias_for)

    unused = set(worker_images.images) - used
    if unused:
        print(
            "Unused worker images detected! "
            + "The following images are not used by any pools:\n\n"
            + "\n".join(sorted(unused))
        )

    assert not unused
