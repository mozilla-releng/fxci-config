import pytest

from ciadmin.generate.ciconfig.projects import Project
from ciadmin.util.matching import feature_match, glob_match


@pytest.mark.parametrize(
    "grantee_values,proj_value,expected_result",
    (
        pytest.param(
            None,
            "foo",
            True,
            id="null_grantees",
        ),
        pytest.param(
            [],
            "foo",
            False,
            id="no_grantees",
        ),
        pytest.param(
            ["*"],
            "foo",
            True,
            id="full_glob_grantee",
        ),
        pytest.param(
            ["foo"],
            "foo",
            True,
            id="exact_string_match",
        ),
        pytest.param(
            ["f*"],
            "foo",
            True,
            id="glob_match",
        ),
        pytest.param(
            ["f*o"],
            "foo",
            False,
            id="glob_only_works_as_last_char",
        ),
        pytest.param(
            ["*oo"],
            "foo",
            False,
            id="glob_doesnt_prefix_match",
        ),
        pytest.param(
            ["foo"],
            "bar",
            False,
            id="exact_string_no_match",
        ),
        pytest.param(
            ["f*"],
            "bar",
            False,
            id="glob_no_match",
        ),
    ),
)
def test_glob_match(grantee_values, proj_value, expected_result):
    assert glob_match(grantee_values, proj_value) == expected_result


def make_project(*features):
    return Project(
        alias="prj",
        branches=[{"name": "default"}],
        repo="https://hg.mozilla.org/prj",
        repo_type="hg",
        access="scm_level_3",
        trust_domain="gecko",
        features={f: True for f in features},
    )


@pytest.mark.parametrize(
    "features, project_features, expected_result",
    (
        pytest.param(None, ["a"], True, id="none"),
        pytest.param(["a"], ["a", "b"], True, id="exact_match"),
        pytest.param(["a"], ["b"], False, id="exact_no_match"),
        pytest.param(["a", "b"], ["a"], False, id="all_required"),
        pytest.param(["!a"], ["a"], False, id="negated"),
        pytest.param(["!a"], ["b"], True, id="negated_absent"),
        pytest.param(["sw-*"], ["sw-signing"], True, id="prefix_match"),
        pytest.param(["sw-*"], ["other"], False, id="prefix_no_match"),
        pytest.param(["sw-*", "a"], ["sw-x"], False, id="prefix_and_exact"),
        pytest.param(["!sw-*"], ["sw-x"], False, id="negated_prefix"),
        pytest.param(["!sw-*"], ["other"], True, id="negated_prefix_absent"),
    ),
)
def test_feature_match(features, project_features, expected_result):
    assert feature_match(features, make_project(*project_features)) == expected_result
