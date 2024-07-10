# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from contextlib import contextmanager

import pytest
from tcadmin.appconfig import AppConfig

from ciadmin.generate.ciconfig import get
from ciadmin.generate.ciconfig.projects import Project


@pytest.fixture
def mock_ciconfig_file():
    """
    Set a mock value for `get_ciconfig_file`.
    """

    def mocker(filename, content):
        get._cache[filename] = content

    yield mocker
    get._cache.clear()


@pytest.fixture
def set_environment():
    @contextmanager
    def set_env(environment):
        config = AppConfig()
        config.options = {"--environment": environment}
        with AppConfig._as_current(config):
            yield

    yield set_env


@pytest.fixture
def sample_projects():
    return [
        Project(
            alias="hg",
            branches=[
                {
                    "name": "default",
                },
            ],
            repo="https://hg.mozilla.org/hg",
            repo_type="hg",
            access="scm_level_1",
            trust_domain="foo",
        ),
        Project(
            alias="limited_branches",
            branches=[
                {
                    "name": "main",
                    "level": 3,
                },
                {
                    "name": "release*",
                    "level": 3,
                },
                {
                    "name": "default",
                    "level": 1,
                },
            ],
            repo="https://github.com/mozilla/example",
            repo_type="git",
            trust_domain="foo",
        ),
        # note: this schema does not allow for a "fallback" level that only applies
        # to branches not explicitly named
        Project(
            alias="star_only",
            branches=[
                {
                    "name": "*",
                    "level": 3,
                },
            ],
            default_branch="main",
            repo="https://github.com/mozilla/example2",
            repo_type="git",
            trust_domain="foo",
        ),
    ]
