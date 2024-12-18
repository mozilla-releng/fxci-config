# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


import copy
from typing import Any


def merge_to(source, dest):
    """
    Merge dict and arrays (override scalar values)

    Keys from source override keys from dest, and elements from lists in source
    are appended to lists in dest.

    :param dict source: to copy from
    :param dict dest: to copy to (modified in place)
    """

    for key, value in source.items():
        # Override mismatching or empty types
        if type(value) != type(dest.get(key)):  # noqa
            dest[key] = source[key]
            continue

        # Merge dict
        if isinstance(value, dict):
            merge_to(value, dest[key])
            continue

        if isinstance(value, list):
            dest[key] = dest[key] + source[key]
            continue

        dest[key] = source[key]

    return dest


def merge(*objects):
    """
    Merge the given objects, using the semantics described for merge_to, with
    objects later in the list taking precedence.  From an inheritance
    perspective, "parents" should be listed before "children".

    Returns the result without modifying any arguments.
    """
    if len(objects) == 1:
        return copy.deepcopy(objects[0])
    return merge_to(objects[-1], merge(*objects[:-1]))


def deep_get(dict_: dict[str, Any], field: str, default: Any|None=None) -> Any:
    """
    Return a key from nested dictionaries using dot path notation
    (e.g "key.subkey").

    Args:
        dict_: The dictionary to retrieve a value from.
        field: The key to retrieve, can use dot path notation.
        default: A default value to return if key does not exist
            (default: None).
    """
    container, subfield = dict_, field
    while "." in subfield:
        f, subfield = subfield.split(".", 1)
        if f not in container:
            return default

        container = container[f]

    return container.get(subfield, default)
