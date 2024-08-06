# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

from pprint import pprint

import pytest
from tcadmin.resources import Resources

from ciadmin.generate import grants
from ciadmin.generate.ciconfig.grants import Grant
from ciadmin.generate.ciconfig.projects import Project
from ciadmin.util.matching import GroupGrantee, ProjectGrantee


@pytest.fixture
def add_scope():
    def add_scope(roleId, scope):
        add_scope.added.add((roleId, scope))

    add_scope.added = set()
    return add_scope


class TestAddScopesForProjects:
    "Tests for add_scopes_to_projects"

    projects = [
        Project(
            alias="proj1",
            repo="https://hg.mozilla.org/foo/proj1",
            repo_type="hg",
            access="scm_level_1",
            branches=[
                {
                    "name": "default",
                },
            ],
            trust_domain="gecko",
            features={"buildbot": False, "travis-ci": True},
        ),
        Project(
            alias="proj2",
            repo="https://hg.mozilla.org/foo/proj2",
            repo_type="hg",
            access="scm_nss",
            branches=[
                {
                    "name": "default",
                },
            ],
            trust_domain="nss",
            is_try=True,
        ),
        Project(
            alias="proj3",
            repo="https://hg.mozilla.org/foo/proj3",
            repo_type="hg",
            access="scm_level_3",
            branches=[
                {
                    "name": "default",
                },
            ],
            trust_domain="comm",
            trust_project="proj3",
        ),
    ]

    def test_no_match(self, add_scope):
        "If no projects match, it does not add scopes"
        grantee = ProjectGrantee(level=2)
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope, self.projects
        )
        assert add_scope.added == set()

    def test_no_scopes(self, add_scope):
        "If a projects matches, but no scopes are granted, nothing happens"
        grantee = ProjectGrantee(level=1)
        grants.add_scopes_for_projects(
            Grant(scopes=[], grantees=[grantee]), grantee, add_scope, self.projects
        )
        assert add_scope.added == set()

    def test_match_access(self, add_scope):
        "If access matches, it adds scopes"
        grantee = ProjectGrantee(access="scm_nss")
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope, self.projects
        )
        assert add_scope.added == set(
            [
                ("repo:hg.mozilla.org/foo/proj2:*", "sc"),
                ("repo:hg.mozilla.org/foo/proj2:branch:default", "sc"),
            ]
        )

    def test_match_level(self, add_scope):
        "If levels match, it adds scopes"
        grantee = ProjectGrantee(level=1)
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope, self.projects
        )
        assert add_scope.added == set([("repo:hg.mozilla.org/foo/proj1:*", "sc")])

    def test_match_levels(self, add_scope):
        "If levels match (with multiple options) it adds scopes"
        grantee = ProjectGrantee(level=[1, 2])
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope, self.projects
        )
        assert add_scope.added == set([("repo:hg.mozilla.org/foo/proj1:*", "sc")])

    def test_match_alias(self, add_scope):
        "If alias matches it adds scopes"
        grantee = ProjectGrantee(alias="proj1")
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope, self.projects
        )
        assert add_scope.added == set(
            [
                ("repo:hg.mozilla.org/foo/proj1:*", "sc"),
                ("repo:hg.mozilla.org/foo/proj1:branch:default", "sc"),
            ]
        )

    def test_match_feature(self, add_scope):
        "If feature matches it adds scopes"
        grantee = ProjectGrantee(feature="travis-ci")
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope, self.projects
        )
        assert add_scope.added == set(
            [
                ("repo:hg.mozilla.org/foo/proj1:*", "sc"),
                ("repo:hg.mozilla.org/foo/proj1:branch:default", "sc"),
            ]
        )

    def test_match_not_feature(self, add_scope):
        "If !feature matches it adds scopes"
        grantee = ProjectGrantee(feature="!travis-ci")
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope, self.projects
        )
        assert add_scope.added == set(
            [
                ("repo:hg.mozilla.org/foo/proj2:*", "sc"),
                ("repo:hg.mozilla.org/foo/proj2:branch:default", "sc"),
                ("repo:hg.mozilla.org/foo/proj3:*", "sc"),
                ("repo:hg.mozilla.org/foo/proj3:branch:default", "sc"),
            ]
        )

    def test_match_is_try_false(self, add_scope):
        "If is_try matches and is false it adds scopes"
        grantee = ProjectGrantee(is_try=False)
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope, self.projects
        )
        assert add_scope.added == set(
            [
                ("repo:hg.mozilla.org/foo/proj1:*", "sc"),
                ("repo:hg.mozilla.org/foo/proj1:branch:default", "sc"),
                ("repo:hg.mozilla.org/foo/proj3:*", "sc"),
                ("repo:hg.mozilla.org/foo/proj3:branch:default", "sc"),
            ]
        )

    def test_match_is_try_true(self, add_scope):
        "If is_try matches and is true it adds scopes"
        grantee = ProjectGrantee(is_try=True)
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope, self.projects
        )
        assert add_scope.added == set(
            [
                ("repo:hg.mozilla.org/foo/proj2:*", "sc"),
                ("repo:hg.mozilla.org/foo/proj2:branch:default", "sc"),
            ]
        )

    def test_match_trust_domain(self, add_scope):
        "If trust_domain matches it adds scopes"
        grantee = ProjectGrantee(trust_domain="gecko")
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope, self.projects
        )
        assert add_scope.added == set(
            [
                ("repo:hg.mozilla.org/foo/proj1:*", "sc"),
                ("repo:hg.mozilla.org/foo/proj1:branch:default", "sc"),
            ]
        )

    def test_match_has_trust_project_true(self, add_scope):
        "If has_trust_project matches and is true it adds scopes"
        grantee = ProjectGrantee(has_trust_project=True)
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope, self.projects
        )
        assert add_scope.added == set(
            [
                ("repo:hg.mozilla.org/foo/proj3:*", "sc"),
                ("repo:hg.mozilla.org/foo/proj3:branch:default", "sc"),
            ]
        )

    def test_match_has_trust_project_false(self, add_scope):
        "If has_trust_project matches and is false it doesn't add scopes"
        grantees = [
            ProjectGrantee(has_trust_project=False),
            ProjectGrantee(),
        ]
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=grantees),
            grantees[0],
            add_scope,
            self.projects,
        )
        assert add_scope.added == set(
            [
                ("repo:hg.mozilla.org/foo/proj1:*", "sc"),
                ("repo:hg.mozilla.org/foo/proj1:branch:default", "sc"),
                ("repo:hg.mozilla.org/foo/proj2:*", "sc"),
                ("repo:hg.mozilla.org/foo/proj2:branch:default", "sc"),
            ]
        )

    def test_scope_substitution(self, add_scope):
        "Values alias, trust_domain, and level are substituted"
        grantee = ProjectGrantee(level=[1, 3])
        grants.add_scopes_for_projects(
            Grant(
                scopes=["foo:{trust_domain}:level:{level}:{alias}:{priority}"],
                grantees=[grantee],
            ),
            grantee,
            add_scope,
            self.projects,
        )
        assert add_scope.added == set(
            [
                ("repo:hg.mozilla.org/foo/proj1:*", "foo:gecko:level:1:proj1:low"),
                ("repo:hg.mozilla.org/foo/proj2:*", "foo:nss:level:3:proj2:highest"),
                ("repo:hg.mozilla.org/foo/proj3:*", "foo:comm:level:3:proj3:highest"),
            ]
        )

    def test_scope_substitution_invalid_key(self, add_scope):
        "Substituting an unknown thing into a scope fails"
        grantee = ProjectGrantee(level=1)
        with pytest.raises(KeyError):
            grants.add_scopes_for_projects(
                Grant(scopes=["foo:{bar}"], grantees=[grantee]),
                grantee,
                add_scope,
                self.projects,
            )

    def test_scope_substitution_no_level(self, add_scope):
        "A project without a level does not substitute {level} (fails)"
        grantee = ProjectGrantee(access="scm_unknown")
        projects = [
            Project(
                alias="proj1",
                repo="https://hg.mozilla.org/foo/proj1",
                repo_type="hg",
                access="scm_unknown",
                branches=[
                    {
                        "name": "default",
                    },
                ],
                trust_domain="crazy",
                features={},
            )
        ]

        with pytest.raises(KeyError):
            grants.add_scopes_for_projects(
                Grant(scopes=["foo:{level}"], grantees=[grantee]),
                grantee,
                add_scope,
                projects,
            )
        with pytest.raises(KeyError):
            grants.add_scopes_for_projects(
                Grant(scopes=["foo:{priority}"], grantees=[grantee]),
                grantee,
                add_scope,
                projects,
            )


class TestAddScopesForGroups:
    "Tests for add_scopes_to_groups"

    def test_no_groups(self, add_scope):
        "If no groups are given, nothing happens"
        grantee = GroupGrantee(groups=[])
        grants.add_scopes_for_groups(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope
        )
        assert add_scope.added == set()

    def test_scopes_added(self, add_scope):
        "scopes are granted to groups, yay"
        grantee = GroupGrantee(groups=["group1", "group2"])
        grants.add_scopes_for_groups(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope
        )
        assert add_scope.added == set(
            [
                ("project:releng:ci-group:group1", "sc"),
                ("project:releng:ci-group:group2", "sc"),
            ]
        )

    def test_substitution_fails(self, add_scope):
        "{..} in scopes is an error for groups"
        grantee = GroupGrantee(groups=["group1", "group2"])
        with pytest.raises(KeyError):
            grants.add_scopes_for_groups(
                Grant(scopes=["level:{level}"], grantees=[grantee]), grantee, add_scope
            )


class TestAddScopesForGithubPullRequest:
    projects = [
        Project(
            alias="hg",
            repo="https://hg.mozilla.org/hg",
            repo_type="hg",
            access="scm_level_1",
            trust_domain="foo",
        ),
        Project(
            alias="no-prs",
            branches=[
                {
                    "name": "main",
                    "level": 3,
                }
            ],
            repo="https://github.com/mozilla/no-prs",
            repo_type="git",
            trust_domain="foo",
        ),
        Project(
            alias="public",
            branches=[
                {
                    "name": "main",
                    "level": 3,
                }
            ],
            repo="https://github.com/mozilla/public",
            repo_type="git",
            trust_domain="foo",
            features={
                "github-pull-request": {
                    "enabled": True,
                    "policy": "public",
                }
            },
        ),
        Project(
            alias="public-restricted",
            branches=[
                {
                    "name": "main",
                    "level": 3,
                }
            ],
            repo="https://github.com/mozilla/public-restricted",
            repo_type="git",
            trust_domain="foo",
            features={
                "github-pull-request": {
                    "enabled": True,
                    "policy": "public_restricted",
                }
            },
        ),
        Project(
            alias="collaborators",
            branches=[
                {
                    "name": "main",
                    "level": 3,
                }
            ],
            repo="https://github.com/mozilla/collaborators",
            repo_type="git",
            trust_domain="foo",
            features={
                "github-pull-request": {
                    "enabled": True,
                    "policy": "collaborators",
                }
            },
        ),
    ]

    def test_grant_to_pull_request_trusted(self, add_scope):
        grantee = ProjectGrantee(job=["pull-request:trusted"])
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope, self.projects
        )
        # Dump expected for copy/paste.
        pprint(add_scope.added)
        assert add_scope.added == set(
            [
                ("repo:github.com/mozilla/public-restricted:pull-request", "sc"),
                ("repo:github.com/mozilla/collaborators:pull-request", "sc"),
            ]
        )

    def test_grant_to_pull_request_untrusted(self, add_scope):
        grantee = ProjectGrantee(job=["pull-request:untrusted"])
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope, self.projects
        )
        # Dump expected for copy/paste.
        pprint(add_scope.added)
        assert add_scope.added == set(
            [
                ("repo:github.com/mozilla/public:pull-request", "sc"),
                (
                    "repo:github.com/mozilla/public-restricted:pull-request-untrusted",
                    "sc",
                ),
            ]
        )

    def test_grant_to_pull_request_star(self, add_scope):
        grantee = ProjectGrantee(job=["pull-request:*"])
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope, self.projects
        )
        # Dump expected for copy/paste.
        pprint(add_scope.added)
        assert add_scope.added == set(
            [
                ("repo:github.com/mozilla/public:pull-request", "sc"),
                ("repo:github.com/mozilla/public-restricted:pull-request", "sc"),
                (
                    "repo:github.com/mozilla/public-restricted:pull-request-untrusted",
                    "sc",
                ),
                ("repo:github.com/mozilla/collaborators:pull-request", "sc"),
            ]
        )

    def test_grant_to_star(self, add_scope):
        grantee = ProjectGrantee(job=["*"])
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope, self.projects
        )
        pr_grants = set([g for g in add_scope.added if "pull-request" in g[0]])

        # Dump expected for copy/paste.
        pprint(pr_grants)
        assert pr_grants == set(
            [
                ("repo:github.com/mozilla/public:pull-request", "sc"),
                ("repo:github.com/mozilla/public-restricted:pull-request", "sc"),
                (
                    "repo:github.com/mozilla/public-restricted:pull-request-untrusted",
                    "sc",
                ),
                ("repo:github.com/mozilla/collaborators:pull-request", "sc"),
            ]
        )

    def test_include_pull_requests_false(self, add_scope):
        grantee = ProjectGrantee(job=["pull-request:*"], include_pull_requests=False)
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]), grantee, add_scope, self.projects
        )
        assert add_scope.added == set()

    def test_invalid_grantee(self):
        grantee = ProjectGrantee(job=["pull-request"])
        with pytest.raises(RuntimeError):
            grants.add_scopes_for_projects(
                Grant(scopes=["sc"], grantees=[grantee]),
                grantee,
                add_scope,
                self.projects,
            )


class TestAddScopesForGithubPush:
    def test_grant_to_all_branches(self, add_scope, sample_projects):
        grantee = ProjectGrantee(alias="limited_branches")
        grants.add_scopes_for_projects(
            Grant(scopes=["sc-{level}"], grantees=[grantee]),
            grantee,
            add_scope,
            sample_projects,
        )
        pprint(add_scope.added)
        assert add_scope.added == set(
            [
                ("repo:github.com/mozilla/example:branch:main", "sc-3"),
                ("repo:github.com/mozilla/example:branch:release*", "sc-3"),
                ("repo:github.com/mozilla/example:branch:default", "sc-1"),
                ("repo:github.com/mozilla/example:release:*", "sc-3"),
            ]
        )

    def test_grant_to_specific_branch(self, add_scope, sample_projects):
        grantee = ProjectGrantee(alias="limited_branches", job=["branch:main"])
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]),
            grantee,
            add_scope,
            sample_projects,
        )
        pprint(add_scope.added)
        assert add_scope.added == set(
            [
                ("repo:github.com/mozilla/example:branch:main", "sc"),
            ]
        )

    def test_grant_to_level(self, add_scope, sample_projects):
        grantee = ProjectGrantee(alias="limited_branches", level=[3])
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]),
            grantee,
            add_scope,
            sample_projects,
        )
        pprint(add_scope.added)
        assert add_scope.added == set(
            [
                ("repo:github.com/mozilla/example:branch:main", "sc"),
                ("repo:github.com/mozilla/example:branch:release*", "sc"),
                ("repo:github.com/mozilla/example:release:*", "sc"),
            ]
        )

    def test_grant_to_branch_and_level(self, add_scope, sample_projects):
        grantee = ProjectGrantee(
            alias="limited_branches", job=["branch:main", "branch:default"], level=[3]
        )
        grants.add_scopes_for_projects(
            Grant(scopes=["sc"], grantees=[grantee]),
            grantee,
            add_scope,
            sample_projects,
        )
        pprint(add_scope.added)
        assert add_scope.added == set(
            [
                ("repo:github.com/mozilla/example:branch:main", "sc"),
            ]
        )

    def test_grant_to_all_branches_with_star(self, add_scope, sample_projects):
        grantee = ProjectGrantee(alias="star_only", job=["branch:*"], level=[3])
        grants.add_scopes_for_projects(
            Grant(scopes=["sc-{level}"], grantees=[grantee]),
            grantee,
            add_scope,
            sample_projects,
        )
        pprint(add_scope.added)
        assert add_scope.added == set(
            [
                ("repo:github.com/mozilla/example2:branch:*", "sc-3"),
            ]
        )


@pytest.mark.asyncio
async def test_update_resources(mock_ciconfig_file, set_environment):
    mock_ciconfig_file(
        "projects.yml",
        {
            "proj1": dict(
                repo="https://hg.mozilla.org/foo/proj1",
                repo_type="hg",
                access="scm_level_1",
                branches=[
                    {
                        "name": "default",
                    },
                ],
                trust_domain="gecko",
            )
        },
    )
    mock_ciconfig_file(
        "grants.yml",
        [
            {
                "grant": ["scope1:xyz", "scope1:abc", "scope2:*"],
                "to": [{"project": {}}],
            },
            {"grant": ["scope1:*", "scope2:abc"], "to": [{"project": {}}]},
        ],
    )
    mock_ciconfig_file(
        "environments.yml",
        {
            "test-env": {
                "root_url": "http://taskcluster/",
                "modify_resources": [],
                "worker_manager": {},
            }
        },
    )

    resources = Resources()
    resources.manage("Role=.*")

    with set_environment("test-env"):
        await grants.update_resources(resources)

    for resource in resources:
        if resource.id == "Role=repo:hg.mozilla.org/foo/proj1:*":
            assert set(resource.scopes) == set(["scope1:*", "scope2:*"])
            break
    else:
        assert 0, "no role defined"
