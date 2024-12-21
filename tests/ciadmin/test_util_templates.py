# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from ciadmin.util.templates import deep_get, merge, merge_to

print(__file__)


def test_merge_to_dicts():
    source = {"a": 1, "b": 2}
    dest = {"b": "20", "c": 30}
    expected = {
        "a": 1,  # source only
        "b": 2,  # source overrides dest
        "c": 30,  # dest only
    }
    assert merge_to(source, dest) == expected
    assert dest == expected


def test_merge_to_lists():
    source = {"x": [3, 4]}
    dest = {"x": [1, 2]}
    expected = {"x": [1, 2, 3, 4]}  # dest first
    assert merge_to(source, dest) == expected
    assert dest == expected


def test_merge_diff_types():
    source = {"x": [1, 2]}
    dest = {"x": "abc"}
    expected = {"x": [1, 2]}  # source wins
    assert merge_to(source, dest) == expected
    assert dest == expected


def test_merge():
    first = {"a": 1, "b": 2, "d": 11}
    second = {"b": 20, "c": 30}
    third = {"c": 300, "d": 400}
    expected = {
        "a": 1,
        "b": 20,
        "c": 300,
        "d": 400,
    }
    assert merge(first, second, third) == expected

    # inputs haven't changed..
    assert first == {"a": 1, "b": 2, "d": 11}
    assert second == {"b": 20, "c": 30}
    assert third == {"c": 300, "d": 400}


@pytest.mark.parametrize(
    "args,expected",
    (
        pytest.param(({}, "foo"), None, id="not found"),
        pytest.param(({}, "foo", True), True, id="not found default"),
        pytest.param(({"foo": "bar"}, "foo"), "bar", id="single"),
        pytest.param(({"foo": {"bar": {"baz": 1}}}, "foo.bar.baz"), 1, id="dot path"),
        pytest.param(
            ({"foo": {"bar": {"baz": 1}}}, "foo.missing.baz"),
            None,
            id="not found middle",
        ),
    ),
)
def test_deep_get(args, expected):
    assert deep_get(*args) == expected
