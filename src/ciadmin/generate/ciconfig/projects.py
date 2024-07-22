# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from typing import List
import attr
from mozilla_repo_urls import parse
from mozilla_repo_urls.parser import RepoUrlParsed

from ...util.matching import glob_match
from .get import get_ciconfig_file

SYMBOLIC_GROUP_LEVELS = {
    "scm_versioncontrol": 3,
    "scm_autoland": 3,
    "scm_nss": 3,
    "scm_allow_direct_push": 3,
    "scm_firefoxci": 3,
}


def _convert_cron_targets(values):
    def convert(value):
        if isinstance(value, str):
            return {"target": value, "bindings": []}
        elif isinstance(value, dict):
            return value
        raise ValueError("Unknowon type of cron target: {!r}".format(value))

    return list(map(convert, values))


@attr.s(frozen=True)
class Branch:
    name: str = attr.ib(type=str)
    level: int = attr.ib(
        type=int,
        default=None,
        validator=[
            attr.validators.optional(attr.validators.instance_of(int)),
            attr.validators.optional(attr.validators.in_([1, 2, 3])),
        ],
    )


@attr.s(frozen=True)
class Project:
    alias: str = attr.ib(type=str)
    repo: str = attr.ib(type=str)
    repo_type: str = attr.ib(type=str)
    access: str = attr.ib(
        type=str,
        default=None,
        validator=attr.validators.optional(attr.validators.instance_of(str)),
    )
    branches: List[Branch] = attr.ib(
        type=list, default=[], converter=lambda b: [Branch(**d) for d in b]
    )
    default_branch: str = attr.ib(
        type=str,
        default=attr.Factory(
            lambda self: "main" if self.repo_type == "git" else "default",
            takes_self=True,
        ),
    )
    trust_domain: str = attr.ib(type=str, default=None)
    trust_project: str = attr.ib(type=str, default=None)
    parent_repo: str = attr.ib(type=str, default=None)
    is_try: bool = attr.ib(type=bool, default=False)
    features: dict = attr.ib(type=dict, factory=lambda: {})
    cron: dict = attr.ib(type=dict, factory=lambda: {})
    taskcluster_yml_project: str = attr.ib(type=str, default=None)

    _parsed_url: RepoUrlParsed = attr.ib(
        eq=False,
        init=False,
        default=attr.Factory(lambda self: parse(self.repo), takes_self=True),
    )
    repo_path: str = attr.ib(
        init=False,
        default=attr.Factory(lambda self: self._parsed_url.repo_path, takes_self=True),
    )
    role_prefix: str = attr.ib(
        init=False,
        default=attr.Factory(
            lambda self: self._parsed_url.taskcluster_role_prefix, takes_self=True
        ),
    )

    def __attrs_post_init__(self):
        """
        Once the object is initialised, perform more sanity checks to ensure
        the values received are sane together
        """
        self.cron["targets"] = _convert_cron_targets(self.cron.get("targets", []))

        # if neither `access` nor `level` are present, bail out
        if not self.access and any([b.level is None for b in self.branches]):
            raise RuntimeError(
                "No access or level specified for project {}".format(self.alias)
            )
        # `access` is mandatory while `level` forbidden for hg based projects
        # and vice-versa for non-hg repositories
        if self.repo_type == "hg":
            if not self.access:
                raise ValueError(
                    "Mercurial repo {} needs to provide an input for "
                    "its `access` value".format(self.alias)
                )
            if any([b.level is not None for b in self.branches]):
                raise ValueError(
                    "Mercurial repo {} cannot define a `level` "
                    "property".format(self.alias)
                )
        else:
            if any([b.level is None for b in self.branches]):
                raise ValueError(
                    "Non-hg repo {} needs to provide an input for "
                    "its `level` value".format(self.alias)
                )
            if self.access:
                raise ValueError(
                    "Non-hg repo {} cannot define an `access` "
                    "property".format(self.alias)
                )

        # Convert boolean features into a dict of the form {"enabled": <val>}
        for name, val in self.features.items():
            if isinstance(val, dict):
                val.setdefault("enabled", True)
            elif isinstance(val, bool):
                self.features[name] = {"enabled": val}
            else:
                raise ValueError("Feature {} must be a dict or boolean".format(name))

    @staticmethod
    async def fetch_all():
        """Load project metadata from projects.yml in ci-configuration"""
        projects = await get_ciconfig_file("projects.yml")
        return [Project(alias, **info) for alias, info in projects.items()]

    @staticmethod
    async def get(alias):
        projects = await Project.fetch_all()

        for project in projects:
            if project.alias == alias:
                return project
        else:
            raise KeyError("Project {} is not defined".format(alias))

    # The `features` property is designed for ease of use in yaml, with true and false
    # values for each feature; the `feature()` and `enabled_features` attributes provide
    # easier access for Python uses.

    def feature(self, feature, key="enabled"):
        "Return True if this feature is enabled"
        return feature in self.features and self.features[feature][key]

    @property
    def enabled_features(self):
        "The list of enabled features"
        return [f for f, val in self.features.items() if val["enabled"]]

    def get_level(self, branch):
        "Get the level, or None if the access level does not define a level"
        if self.access and self.access.startswith("scm_level_"):
            return int(self.access[-1])
        elif self.access and self.access in SYMBOLIC_GROUP_LEVELS:
            return SYMBOLIC_GROUP_LEVELS[self.access]
        else:
            for b in self.branches:
                if glob_match([b.name], branch):
                    return b.level

            return None

    @property
    def default_branch_level(self):
        return self.get_level(self.default_branch)
