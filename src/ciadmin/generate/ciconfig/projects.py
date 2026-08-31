# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import re
from functools import cached_property

import attr
from mozilla_repo_urls import parse

from ...util.matching import glob_match
from .get import get_ciconfig_file

SYMBOLIC_GROUP_LEVELS = {
    "scm_versioncontrol": 3,
    "scm_autoland": 3,
    "scm_nss": 3,
    "scm_allow_direct_push": 3,
    "scm_firefoxci": 3,
}
CRON_BRANCH_RE = re.compile(r"^[A-Za-z0-9_-]+$")


CRON_TARGET_KEYS = {"target", "bindings", "allow-input"}


def _level_from_access(access):
    "Derive an scm level from a project's `access` value, or None if not possible"
    if not access:
        return None
    if access.startswith("scm_level_"):
        return int(access[-1])
    return SYMBOLIC_GROUP_LEVELS.get(access)


def _convert_cron_targets(values):
    def convert(value):
        if isinstance(value, str):
            return {"target": value, "bindings": []}
        elif isinstance(value, dict):
            unknown = set(value) - CRON_TARGET_KEYS
            if unknown == {"branch"}:
                raise ValueError(
                    f"Cron target {value.get('target')!r} cannot set `branch`. "
                    "Mark the branches to run cron on with `cron: true` in the "
                    "project's `branches` instead."
                )
            if unknown:
                raise ValueError(
                    f"Unknown keys in cron target {value.get('target')!r}: "
                    f"{sorted(unknown)}"
                )
            return value
        raise ValueError(f"Unknowon type of cron target: {value!r}")

    return list(map(convert, values))


@attr.s(frozen=True)
class Branch:
    name = attr.ib(type=str)
    level = attr.ib(
        type=int,
        default=None,
        validator=[
            attr.validators.optional(attr.validators.instance_of(int)),
            attr.validators.optional(attr.validators.in_([1, 2, 3])),
        ],
    )
    cron = attr.ib(type=bool, default=False)


@attr.s(frozen=True)
class Project:
    alias = attr.ib(type=str)
    repo = attr.ib(type=str)
    repo_type = attr.ib(type=str)
    access = attr.ib(
        type=str,
        default=None,
        validator=attr.validators.optional(attr.validators.instance_of(str)),
    )
    branches = attr.ib(
        type=list, default=[], converter=lambda b: [Branch(**d) for d in b]
    )
    _default_branch = attr.ib(
        type=str,
        default=attr.Factory(
            lambda self: "main" if self.repo_type == "git" else "default",
            takes_self=True,
        ),
    )
    lando_repo = attr.ib(type=str, default=None)
    trust_domain = attr.ib(type=str, default=None)
    trust_project = attr.ib(type=str, default=None)
    parent_repo = attr.ib(type=str, default=None)
    is_try = attr.ib(type=bool, default=False)
    features = attr.ib(type=dict, factory=lambda: {})
    cron = attr.ib(type=dict, factory=lambda: {})

    _parsed_url = attr.ib(
        eq=False,
        init=False,
        default=attr.Factory(lambda self: parse(self.repo), takes_self=True),
    )
    repo_path = attr.ib(
        init=False,
        default=attr.Factory(lambda self: self._parsed_url.repo_path, takes_self=True),
    )
    role_prefix = attr.ib(
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

        explicit_levels = [b.level is not None for b in self.branches]

        for branch in self.branches:
            if branch.cron and not CRON_BRANCH_RE.match(branch.name):
                raise ValueError(
                    f"Invalid cron branch {branch.name!r} in project {self.alias}: "
                    "cron branches cannot be globs and may only contain "
                    "letters, digits, hyphens and underscores"
                )

        # if neither `access` nor `level` are present, bail out
        if not self.access and not all(explicit_levels):
            raise RuntimeError(f"No access or level specified for project {self.alias}")
        # `access` is mandatory while `level` forbidden for hg based projects
        # and vice-versa for non-hg repositories
        if self.repo_type == "hg":
            if not self.access:
                raise ValueError(
                    f"Mercurial repo {self.alias} needs to provide an input for "
                    "its `access` value"
                )
            if any(explicit_levels):
                raise ValueError(
                    f"Mercurial repo {self.alias} cannot define a `level` property"
                )
        else:
            if not all(explicit_levels):
                raise ValueError(
                    f"Non-hg repo {self.alias} needs to provide an input for "
                    "its `level` value"
                )
            if self.access:
                raise ValueError(
                    f"Non-hg repo {self.alias} cannot define an `access` property"
                )

        # derive each branch's level from `access`, if not already set explicitly
        for i, branch in enumerate(self.branches):
            if branch.level:
                continue

            if level := _level_from_access(self.access):
                self.branches[i] = attr.evolve(branch, level=level)

        # Convert boolean features into a dict of the form {"enabled": <val>}
        for name, val in self.features.items():
            if isinstance(val, dict):
                val.setdefault("enabled", True)
            elif isinstance(val, bool):
                self.features[name] = {"enabled": val}
            else:
                raise ValueError(f"Feature {name} must be a dict or boolean")

        # checked last, because it relies on the features above being converted
        if self.feature("taskgraph-cron"):
            if not any(b.cron for b in self.branches):
                raise ValueError(
                    f"Project {self.alias} runs cron and must mark at least one "
                    "branch with `cron: true`"
                )

            # Reject cron branches below the project's `default_branch.level`.
            if self.default_branch.level is None:
                raise ValueError(
                    f"Project {self.alias} runs cron but its default branch "
                    f"{self.default_branch.name!r} is not matched by any entry in "
                    "`branches`, so it has no level"
                )

            for branch in self.branches:
                if not branch.cron:
                    continue

                if branch.level < self.default_branch.level:
                    raise ValueError(
                        f"Project {self.alias} must not have cron branch '{branch.name}' "
                        f"with lower level than default branch '{self.default_branch.name}'."
                    )

    @staticmethod
    async def fetch_all():
        """Load project metadata from projects.yml in fxci-config"""
        projects = await get_ciconfig_file("projects.yml")
        return [Project(alias, **info) for alias, info in projects.items()]

    @staticmethod
    async def get(alias):
        projects = await Project.fetch_all()

        for project in projects:
            if project.alias == alias:
                return project
        else:
            raise KeyError(f"Project {alias} is not defined")

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

    def get_branch(self, name: str):
        """Get the branch object given a name."""
        for branch in self.branches:
            if glob_match([branch.name], name):
                return branch

    @cached_property
    def default_branch(self):
        matched = self.get_branch(self._default_branch)
        if matched is None:
            return Branch(
                name=self._default_branch, level=_level_from_access(self.access)
            )
        if matched.name == self._default_branch:
            return matched
        # `matched` came from a glob (eg. a `"*"` entry), so its `name` isn't
        # the default branch's actual name
        return attr.evolve(matched, name=self._default_branch)
