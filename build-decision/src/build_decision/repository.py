# -*- coding: utf-8 -*-

# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import logging

import attr
import redo
import yaml

from .util.http import SESSION

logger = logging.getLogger(__name__)


class RetryableError(Exception):
    """
    An error that can automatially be retried.
    """


@attr.s(frozen=True)
class Repository:
    repo_url = attr.ib()
    repository_type = attr.ib()
    project = attr.ib(default=None)
    level = attr.ib(default=None)
    trust_domain = attr.ib(default=None)
    github_token = attr.ib(default=None)

    def get_file(self, path, *, revision=None):
        """
        Get `.taskcluster.yml` from 'default' (or the given revision) at the named
        repo_path.  Note that this does not parse the yml (so that it can be hashed
        in its original form).

        If the file is not found, this returns None.
        """
        if self.repository_type == "hg":
            if revision is None:
                revision = "default"
            url = f"{self.repo_url}/raw-file/{revision}/{path}"
        elif self.repository_type == "git":
            repo_url = self.repo_url
            if revision is None:
                revision = "master"  # FIXME: Use api to get default branch
            if repo_url.startswith("https://github.com/"):
                if repo_url.endswith("/"):
                    repo_url = repo_url[:-1]
                url = f"{repo_url}/raw/{revision}/{path}"
            elif repo_url.startswith("git@github.com:"):
                raise Exception(
                    "Don't know how to get file from private github "
                    "repo: {}".format(repo_url)
                )
            else:
                raise Exception(
                    "Don't know how to determine get file for non-github "
                    "repo: {}".format(repo_url)
                )
        else:
            raise Exception("Unknown repository_type {}!".format(self.repository_type))

        res = SESSION.get(url)
        res.raise_for_status()
        tcyml = res.text
        return yaml.safe_load(tcyml)

    @redo.retriable(attempts=5, sleeptime=10, retry_exceptions=(RetryableError,))
    def get_push_info(self, *, revision=None, branch=None):
        if branch and revision:
            raise ValueError("Can't pass both revision and branch to get_push_info")
        if self.repository_type == "hg":
            if revision:
                revset = revision
            elif branch:
                revset = branch
            else:
                revset = "default"
            res = SESSION.get(
                "{}/json-pushes?version=2&changeset={}&tipsonly=1".format(
                    self.repo_url, revset
                )
            )
            res.raise_for_status()
            pushes = res.json()["pushes"]
            if len(pushes) == 0:
                # If we query immediately after a push, hg.mozilla.org might
                # report that there are no pushes associated to a changeset.
                # We retry, since this tends to be a transient error.
                raise RetryableError(
                    f"Changeset {revset} has no associated pushes. "
                    "Maybe the push log has not been updated?"
                )
            elif len(pushes) != 1:
                raise ValueError(
                    f"Changeset {revset} has {len(pushes)} associated pushes; "
                    "only one supported."
                )
            [(push_id, push_info)] = pushes.items()
            if revision and revision not in push_info["changesets"]:
                raise ValueError(
                    "Changeset {} is not the tip {} of the associated push.".format(
                        revision, push_info["changesets"][0]
                    )
                )
            [revision] = push_info["changesets"]
            return {
                "owner": push_info["user"],
                "pushlog_id": push_id,
                "pushdate": push_info["date"],
                "revision": revision,
            }
        elif self.repository_type == "git":
            if revision:
                raise Exception("Can't get push information for a git revision.")
            if branch is None:
                branch = "master"  # FIXME: Use api to get default branch
            repo_url = self.repo_url
            headers = {}
            if self.github_token:
                headers["Authorization"] = "token {}".format(self.github_token)
            if repo_url.startswith("https://github.com/"):
                url = (
                    f"https://api.github.com"
                    f"/repos/{self.repo_path}/git/ref/heads/{branch}"
                )
                res = SESSION.get(url, headers=headers)
                res.raise_for_status()
                return {
                    "branch": branch,
                    "revision": res.json()["object"]["sha"],
                }
            elif repo_url.startswith("git@github.com:"):
                raise Exception(
                    "Don't know how to determine revision for private github "
                    "repo: {}".format(repo_url)
                )
            else:
                raise Exception(
                    "Don't know how to determine revision for for non-github "
                    "repo: {}".format(repo_url)
                )
        else:
            raise Exception("Unknown repository_type {}!".format(self.repository_type))

    @property
    def repo_path(self):
        if self.repository_type == "hg" and self.repo_url.startswith(
            "https://hg.mozilla.org/"
        ):
            return self.repo_url.replace("https://hg.mozilla.org/", "", 1).rstrip("/")
        elif self.repository_type == "git" and self.repo_url.startswith(
            "https://github.com/"
        ):
            return self.repo_url.replace("https://github.com/", "", 1).rstrip("/")
        else:
            raise AttributeError(
                "no repo_path available for project {}".format(self.alias)
            )

    def to_json(self):
        return {
            "url": self.repo_url,
            "project": self.project,
            "level": self.level,
        }
