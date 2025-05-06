# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import re


def keymatch(attributes, target):
    """
    Determine if any keys in attributes are a match to target, then return
    a list of matching values. First exact matches will be checked. Failing
    that, regex matches and finally a default key.
    """
    # exact match
    if target in attributes:
        return [attributes[target]]

    # regular expression match
    matches = [v for k, v in attributes.items() if re.match(k + "$", target)]
    if matches:
        return matches

    # default
    if "default" in attributes:
        return [attributes["default"]]

    return []


def iter_dot_path(container, subfield):
    while "." in subfield:
        f, subfield = subfield.split(".", 1)

        if f not in container:
            return

        if isinstance(container[f], list):
            if f not in container:
                return

            for item in container[f]:
                yield from iter_dot_path(item, subfield)
            return

        container = container[f]

    if subfield in container:
        yield container, subfield


def resolve_keyed_by(item, field, item_name, **extra_values):
    """
    For values which can either accept a literal value, or be keyed by some
    other attribute of the item, perform that lookup and replacement in-place
    (modifying `item` directly).  The field is specified using dotted notation
    to traverse dictionaries.

    For example, given item::

        task:
            test-platform: linux128
            chunks:
                by-test-platform:
                    macosx-10.11/debug: 13
                    win.*: 6
                    default: 12

    a call to `resolve_keyed_by(item, 'task.chunks', item['thing-name'])`
    would mutate item in-place to::

        task:
            test-platform: linux128
            chunks: 12

    The `item_name` parameter is used to generate useful error messages.

    If extra_values are supplied, they represent additional values available
    for reference from by-<field>.

    Items can be nested as deeply as the schema will allow::

        chunks:
            by-test-platform:
                win.*:
                    by-project:
                        ash: ..
                        cedar: ..
                linux: 13
                default: 12

    Args:
        item (dict): Object being evaluated.
        field (str): Name of the key to perform evaluation on.
        item_name (str): Used to generate useful error messages.
        extra_values (kwargs):
            If supplied, represent additional values available
            for reference from by-<field>.

    Returns:
        dict: item which has also been modified in-place.
    """
    # find the field, returning the item unchanged if anything goes wrong
    container, subfield = item, field
    while "." in subfield:
        f, subfield = subfield.split(".", 1)
        if f not in container:
            return item
        container = container[f]
        if not isinstance(container, dict):
            return item

    if subfield not in container:
        return item

    container[subfield] = evaluate_keyed_by(
        value=container[subfield],
        item_name=f"`{field}` in `{item_name}`",
        attributes=dict(item, **extra_values),
    )

    return item


def evaluate_keyed_by(value, item_name, attributes):
    """
    For values which can either accept a literal value, or be keyed by some
    attributes, perform that lookup and return the result.

    For example, given item::

        by-test-platform:
            macosx-10.11/debug: 13
            win.*: 6
            default: 12

    a call to `evaluate_keyed_by(item, 'thing-name', {'test-platform': 'linux96')`
    would return `12`.

    The `item_name` parameter is used to generate useful error messages.
    Items can be nested as deeply as desired::

        by-test-platform:
            win.*:
                by-project:
                    ash: ..
                    cedar: ..
            linux: 13
            default: 12
    """
    while True:
        if (
            not isinstance(value, dict)
            or len(value) != 1
            or not list(value.keys())[0].startswith("by-")
        ):
            return value

        keyed_by = list(value.keys())[0][3:]  # strip off 'by-' prefix
        key = attributes.get(keyed_by)
        alternatives = list(value.values())[0]

        if len(alternatives) == 1 and "default" in alternatives:
            # Error out when only 'default' is specified as only alternatives,
            # because we don't need to by-{keyed_by} there.
            raise Exception(
                f"Keyed-by '{keyed_by}' unnecessary with only value 'default' "
                f"found, when determining item {item_name}"
            )

        if key is None:
            if "default" in alternatives:
                value = alternatives["default"]
                continue
            else:
                raise Exception(
                    f"No attribute {keyed_by} and no value for 'default' found "
                    f"while determining item {item_name}"
                )

        matches = keymatch(alternatives, key)
        if len(matches) > 1:
            raise Exception(
                f"Multiple matching values for {keyed_by} {key!r} found while "
                f"determining item {item_name}"
            )
        elif matches:
            value = matches[0]
            continue

        raise Exception(
            f"No {keyed_by} matching {key!r} nor 'default' found while determining item {item_name}"
        )
