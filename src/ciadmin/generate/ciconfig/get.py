# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import os
from asyncio import Lock

import yaml

_cache = {}
_lock = {}


async def _read_file(filename, **test_kwargs):
    with open(filename, "rb") as f:
        result = f.read()

    if filename.endswith(".yml"):
        result = yaml.safe_load(result)

    return result


async def get_ciconfig_file(filename):
    """
    Get the named file from the fxci-config repository, parsing .yml if necessary.

    Fetches are cached, so it's safe to call this many times for the same file.
    """
    async with _lock.setdefault(filename, Lock()):
        if filename in _cache:
            return _cache[filename]

        _cache[filename] = await _read_file(filename)
        return _cache[filename]


async def get_ciconfig_dir(dirname):
    """
    Get all .yml files from a directory in the fxci-config repository.
    
    Returns the same type as if one of the individual files was loaded:
    - If all files contain top-level dicts, returns a single merged dict
    - If all files contain top-level lists, returns a single concatenated list
    - Raises ValueError if files contain mixed types or no data is loaded
    
    Results are cached, so it's safe to call this many times for the same directory.
    """
    cache_key = f"dir:{dirname}"
    async with _lock.setdefault(cache_key, Lock()):
        if cache_key in _cache:
            return _cache[cache_key]

        if not os.path.isdir(dirname):
            raise ValueError(f"Directory not found: {dirname}")

        # Get all .yml files in the directory, sorted for consistent ordering
        yml_files = sorted([f for f in os.listdir(dirname) if f.endswith(".yml")])
        
        if not yml_files:
            raise ValueError(f"No .yml files found in directory: {dirname}")

        # Process files and track their types and names
        dict_files = []
        list_files = []
        other_files = []
        
        for yml_file in yml_files:
            file_path = os.path.join(dirname, yml_file)
            file_content = await _read_file(file_path)
            
            if isinstance(file_content, dict):
                dict_files.append((yml_file, file_content))
            elif isinstance(file_content, list):
                list_files.append((yml_file, file_content))
            else:
                other_files.append((yml_file, file_content))

        if other_files:
            raise ValueError(f"Files in directory {dirname} contain unsupported types (not dict or list): {[of[0] for of in other_files]}")

        if dict_files and list_files:
            raise ValueError(f"Directory {dirname} contains mixed file types (both dicts and lists)")

        if dict_files:
            # Merge all dictionaries, checking for duplicate keys
            result = {}
            key_to_file = {}
            for filename, content in dict_files:
                for key, value in content.items():
                    if key in result:
                        raise ValueError(f"Duplicate key '{key}' found in files {key_to_file[key]} and {filename}")
                    result[key] = value
                    key_to_file[key] = filename
        else:
            # Concatenate all lists
            result = []
            for _, content in list_files:
                result.extend(content)

        if not result:
            raise ValueError(f"No valid data loaded from directory: {dirname}")

        _cache[cache_key] = result
        return result
