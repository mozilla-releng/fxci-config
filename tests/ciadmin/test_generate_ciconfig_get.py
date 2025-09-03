# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import os
import tempfile

import pytest
from tcadmin.util.sessions import with_aiohttp_session

from ciadmin.generate.ciconfig.get import _read_file, get_ciconfig_dir


@pytest.mark.asyncio
@with_aiohttp_session
async def test_get_yml():
    res = await _read_file("tests/ciadmin/test.yml")
    assert res == {"test": True}


@pytest.mark.asyncio
@with_aiohttp_session
async def test_get_data():
    res = await _read_file("tests/ciadmin/test_generate_ciconfig_get.py")
    assert b"this one weird string" in res


@pytest.mark.asyncio
@with_aiohttp_session
async def test_get_ciconfig_dir_dicts():
    """Test get_ciconfig_dir with files containing top-level dicts"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files with dicts
        file1_path = os.path.join(tmpdir, "file1.yml")
        with open(file1_path, "w") as f:
            f.write("key1: value1\nkey2: value2\n")

        file2_path = os.path.join(tmpdir, "file2.yml")
        with open(file2_path, "w") as f:
            f.write("key3: value3\nkey4: value4\n")

        result = await get_ciconfig_dir(tmpdir)
        expected = {
            "key1": "value1",
            "key2": "value2",
            "key3": "value3",
            "key4": "value4",
        }
        assert result == expected
        assert isinstance(result, dict)


@pytest.mark.asyncio
@with_aiohttp_session
async def test_get_ciconfig_dir_lists():
    """Test get_ciconfig_dir with files containing top-level lists"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files with lists
        file1_path = os.path.join(tmpdir, "file1.yml")
        with open(file1_path, "w") as f:
            f.write("- item1\n- item2\n")

        file2_path = os.path.join(tmpdir, "file2.yml")
        with open(file2_path, "w") as f:
            f.write("- item3\n- item4\n")

        result = await get_ciconfig_dir(tmpdir)
        expected = ["item1", "item2", "item3", "item4"]
        assert result == expected
        assert isinstance(result, list)


@pytest.mark.asyncio
@with_aiohttp_session
async def test_get_ciconfig_dir_mixed_types_error():
    """Test get_ciconfig_dir raises error with mixed dict/list files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create one dict file and one list file
        file1_path = os.path.join(tmpdir, "file1.yml")
        with open(file1_path, "w") as f:
            f.write("key1: value1\n")

        file2_path = os.path.join(tmpdir, "file2.yml")
        with open(file2_path, "w") as f:
            f.write("- item1\n")

        with pytest.raises(ValueError, match="contains mixed file types"):
            await get_ciconfig_dir(tmpdir)


@pytest.mark.asyncio
@with_aiohttp_session
async def test_get_ciconfig_dir_no_yml_files_error():
    """Test get_ciconfig_dir raises error when no .yml files found"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a non-yml file
        file_path = os.path.join(tmpdir, "file.txt")
        with open(file_path, "w") as f:
            f.write("not yaml")

        with pytest.raises(ValueError, match="No .yml files found"):
            await get_ciconfig_dir(tmpdir)


@pytest.mark.asyncio
@with_aiohttp_session
async def test_get_ciconfig_dir_nonexistent_directory_error():
    """Test get_ciconfig_dir raises error for non-existent directory"""
    with pytest.raises(ValueError, match="Directory not found"):
        await get_ciconfig_dir("/nonexistent/directory")


@pytest.mark.asyncio
@with_aiohttp_session
async def test_get_ciconfig_dir_unsupported_types_error():
    """Test get_ciconfig_dir raises error with unsupported data types"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create file with string content (unsupported type)
        file_path = os.path.join(tmpdir, "file.yml")
        with open(file_path, "w") as f:
            f.write("just a string\n")

        with pytest.raises(ValueError, match="contain unsupported types"):
            await get_ciconfig_dir(tmpdir)


@pytest.mark.asyncio
@with_aiohttp_session
async def test_get_ciconfig_dir_duplicate_keys_error():
    """Test that dict merging throws error on duplicate keys"""
    with tempfile.TemporaryDirectory() as tmpdir:
        file1_path = os.path.join(tmpdir, "file1.yml")
        with open(file1_path, "w") as f:
            f.write("key1: value1\nshared: from_file1\n")

        file2_path = os.path.join(tmpdir, "file2.yml")
        with open(file2_path, "w") as f:
            f.write("key2: value2\nshared: from_file2\n")

        with pytest.raises(
            ValueError,
            match="Duplicate key 'shared' found in files file1.yml and file2.yml",
        ):
            await get_ciconfig_dir(tmpdir)


@pytest.mark.asyncio
@with_aiohttp_session
async def test_get_ciconfig_dir_empty_files():
    """Test get_ciconfig_dir with empty yml files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create yml files with empty dicts
        file1_path = os.path.join(tmpdir, "empty1.yml")
        with open(file1_path, "w") as f:
            f.write("{}")

        file2_path = os.path.join(tmpdir, "empty2.yml")
        with open(file2_path, "w") as f:
            f.write("{}")

        with pytest.raises(ValueError, match="No valid data loaded"):
            await get_ciconfig_dir(tmpdir)
