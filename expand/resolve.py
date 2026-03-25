"""Value resolver for by-level, by-trust-domain, by-cot expressions.

Resolves compressed config values against a PoolGroup's properties.
All by-* dicts resolve to concrete scalars. Supports nesting.
"""

_RESOLVERS = {
    "by-level": lambda pg: pg.level,
    "by-trust-domain": lambda pg: pg.trust_domain,
    "by-cot": lambda pg: "trusted" if pg.cot else "default",
}


def resolve_value(value, pool_group):
    if not isinstance(value, dict):
        return value

    keys = list(value.keys())
    if len(keys) == 1 and keys[0] in _RESOLVERS:
        by_key = keys[0]
        alternatives = value[by_key]
        lookup = _RESOLVERS[by_key](pool_group)

        for alt_key, alt_value in alternatives.items():
            if alt_key == "default":
                continue
            if str(alt_key) == str(lookup):
                return resolve_value(alt_value, pool_group)

        if "default" in alternatives:
            return resolve_value(alternatives["default"], pool_group)

        raise KeyError(
            f"No match for {by_key}={lookup!r} in {list(alternatives.keys())} "
            f"and no default (pool-group: {pool_group.name})"
        )

    return {k: resolve_value(v, pool_group) for k, v in value.items()}
