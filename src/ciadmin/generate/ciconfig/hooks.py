# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import attr

from .get import get_ciconfig_file


@attr.s(frozen=True)
class Hook:
    hook_group_id: str= attr.ib(type=str)
    hook_id: str = attr.ib(type=str)
    name: str = attr.ib(type=str)
    description: str = attr.ib(type=str)
    owner: str = attr.ib(type=str)
    email_on_error: bool = attr.ib(type=bool)
    scopes: list = attr.ib(type=list)
    template_file: str = attr.ib(type=str)
    trigger_schema: dict = attr.ib(type=dict, factory=lambda: {})
    schedule: list = attr.ib(type=list, factory=lambda: [])
    bindings: list = attr.ib(type=list, factory=lambda: [])

    @staticmethod
    async def fetch_all():
        """Load hook metadata from hooks.yml in ci-configuration"""
        hooks = await get_ciconfig_file("hooks.yml")

        for hook_name in hooks:
            if hook_name.count("/") < 1:
                raise ValueError("hook name must be of the form `hookGroupId/hookDi`")

        def hgid(hook_name):
            return hook_name.split("/", 1)[0]

        def hid(hook_name):
            return hook_name.split("/", 1)[1]

        return [
            Hook(hook_group_id=hgid(hook_name), hook_id=hid(hook_name), **info)
            for hook_name, info in hooks.items()
        ]
