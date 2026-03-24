# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from ciadmin.util.templates import deep_get, merge, merge_to, template_merge

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


class TestTemplateMerge:
    def test_dict_merge(self):
        parent = {"a": 1, "b": {"x": 10, "y": 20}}
        child = {"b": {"y": 30, "z": 40}, "c": 3}
        result = template_merge(parent, child)
        assert result == {"a": 1, "b": {"x": 10, "y": 30, "z": 40}, "c": 3}

    def test_list_replacement(self):
        parent = {"items": [1, 2, 3]}
        child = {"items": [4, 5]}
        result = template_merge(parent, child)
        assert result == {"items": [4, 5]}

    def test_child_overrides_scalar(self):
        parent = {"x": "old", "y": "keep"}
        child = {"x": "new"}
        result = template_merge(parent, child)
        assert result == {"x": "new", "y": "keep"}

    def test_parent_only_fields_preserved(self):
        parent = {"a": 1, "b": 2}
        child = {"b": 3}
        result = template_merge(parent, child)
        assert result == {"a": 1, "b": 3}

    def test_no_mutation(self):
        parent = {"a": [1], "b": {"x": 1}}
        child = {"a": [2], "b": {"y": 2}}
        parent_copy = {"a": [1], "b": {"x": 1}}
        child_copy = {"a": [2], "b": {"y": 2}}
        template_merge(parent, child)
        assert parent == parent_copy
        assert child == child_copy

    def test_empty_child(self):
        parent = {"a": 1, "b": [1, 2]}
        result = template_merge(parent, {})
        assert result == parent
        assert result is not parent

    def test_nested_list_in_dict(self):
        parent = {"config": {"instance_types": [{"type": "a"}], "maxCapacity": 10}}
        child = {"config": {"instance_types": [{"type": "b"}]}}
        result = template_merge(parent, child)
        assert result == {
            "config": {"instance_types": [{"type": "b"}], "maxCapacity": 10}
        }
