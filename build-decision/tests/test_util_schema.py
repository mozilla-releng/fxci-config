# coding=utf-8

import pytest

import build_decision.util.schema as schema


def test_local_ref_resolver():
    """Add coverage to util.schema.LocalRefResolver.resolve_remote."""
    resolver = schema.LocalRefResolver("base_uri", "referrer")
    with pytest.raises(Exception):
        resolver.resolve_remote("remote")
