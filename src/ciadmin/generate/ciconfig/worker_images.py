# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from typing import Any

import attr

from ciadmin.generate.ciconfig.get import get_ciconfig_file
from ciadmin.util.templates import deep_get


@attr.s(frozen=True)
class WorkerImage:
    image_name = attr.ib(type=str)
    alias_for = attr.ib(type=str, default=None)
    clouds = attr.ib(type=dict, default={})

    @staticmethod
    async def fetch_all():
        """
        Load worker-image metadata from worker-images.yml in fxci-config,
        returning a WorkerImages instance that will resolve aliases.
        """
        worker_images = await get_ciconfig_file("worker-images.yml")

        def mk(image_name, info):
            if isinstance(info, str):
                return WorkerImage(image_name=image_name, alias_for=info)
            else:
                return WorkerImage(image_name=image_name, clouds=info)

        return WorkerImages(
            [mk(image_name, info) for image_name, info in worker_images.items()]
        )

    def get(
        self, cloud: str, key: str | None = None, default: Any | None = None
    ) -> Any:
        """
        Look up a key under the given cloud config for this worker image.

        Args:
            cloud (str): The cloud provider (provider_id) to obtain data from.
            key (str): The key to obtain a value from (optional).
                If not specified then the entire value of the specified cloud is returned. If
                specified, the value of the matching key will be obtained. This can optionally
                use dot path notation (e.g "key.subkey") to obtain a value from nested
                dictionaries. If the key or any nested subkey along the dot path does not exist,
                `None` is returned.

        Returns:
            Any: The value defined under the specified cloud.
        """
        if cloud not in self.clouds:
            raise KeyError(
                f"{cloud} not present for {self.image_name} - "
                "maybe you need to update worker-images.yml?"
            )
        cfg = self.clouds[cloud]
        if not key:
            return cfg

        return deep_get(cfg, key, default)


class WorkerImages:
    def __init__(self, images):
        self.images = {i.image_name: i for i in images}

    def __getitem__(self, image_name):
        "Retrive a WorkerImage, accounting for aliases"
        while True:
            image = self.images[image_name]
            if not image.alias_for:
                return image
            image_name = image.alias_for

    def get(self, image_name, default=None):
        try:
            return self[image_name]
        except KeyError:
            return default
