# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import attr
from tcadmin.appconfig import AppConfig

from .get import get_ciconfig_file


@attr.s(frozen=True)
class Environment:
    # Environment name
    name = attr.ib(type=str)

    # Root URL for this environment
    root_url = attr.ib(type=str)

    # List of modifications to make to the generated resources for this
    # environment.  This is useful, for example, for modifying staging
    # environments to consume fewer resources.
    modify_resources = attr.ib(type=list)

    worker_manager = attr.ib(type=dict)
    aws_config = attr.ib(type=dict, factory=lambda: {})
    google_config = attr.ib(type=dict, factory=lambda: {})
    cron = attr.ib(type=dict, factory=lambda: {})

    @staticmethod
    async def fetch_all():
        """Load project metadata from projects.yml in ci-configuration"""
        environments = await get_ciconfig_file("environments.yml")
        return [
            Environment(environment_name, **info)
            for environment_name, info in environments.items()
        ]

    @staticmethod
    async def get(environment_name):
        environments = await Environment.fetch_all()

        for environment in environments:
            if environment.name == environment_name:
                return environment
        else:
            raise KeyError("Environment {} is not defined".format(environment_name))

    @staticmethod
    def current():
        environment_name = AppConfig.current().options.get("--environment")
        return Environment.get(environment_name)
