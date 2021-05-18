# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


from __future__ import absolute_import, print_function, unicode_literals

import attr
import yaml
from jsonschema.validators import RefResolver, validator_for


class LocalRefResolver(RefResolver):
    def resolve_remote(self, uri):
        raise Exception("Can't resolve remote schema.")


def _get_validator(schema):
    resolver = LocalRefResolver.from_schema(schema)
    cls = validator_for(schema)
    cls.check_schema(schema)
    return cls(schema, resolver=resolver)


@attr.s(frozen=True)
class Schema:
    _schema = attr.ib()
    _validator = attr.ib(
        init=False,
        default=attr.Factory(
            lambda self: _get_validator(self._schema), takes_self=True
        ),
    )

    @classmethod
    def from_file(cls, path):
        schema = yaml.safe_load(path.read_text())
        return cls(schema)

    def validate(self, value):
        self._validator.validate(value)
