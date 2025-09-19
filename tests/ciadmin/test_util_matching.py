import pytest

from ciadmin.util.matching import glob_match


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
        # Tests for None value handling
        pytest.param(
            ["*"],
            None,
            False,
            id="wildcard_does_not_match_none",
        ),
        pytest.param(
            ["foo"],
            None,
            False,
            id="specific_value_does_not_match_none",
        ),
        pytest.param(
            ["foo*"],
            None,
            False,
            id="prefix_wildcard_does_not_match_none",
        ),
    ),
)
def test_glob_match(grantee_values, proj_value, expected_result):
    assert glob_match(grantee_values, proj_value) == expected_result
