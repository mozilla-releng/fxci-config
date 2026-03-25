"""Load and expand pool-group definitions from pool-groups.yml."""
import attr
import yaml


@attr.s(frozen=True)
class PoolGroup:
    """A single expanded pool-group with its derived properties."""
    name = attr.ib(type=str)
    trust_domain = attr.ib(type=str)
    level = attr.ib()  # int (1,2,3) or str ("t", "standalone")
    cot = attr.ib(type=bool)


def load_pool_groups(config):
    result = {}
    for domain, props in config["pool-groups"].items():
        levels = props.get("levels", [])
        testing = props.get("testing", False)
        for level in levels:
            if level == "standalone":
                name = domain
                result[name] = PoolGroup(name=name, trust_domain=domain, level="standalone", cot=False)
            else:
                name = f"{domain}-{level}"
                result[name] = PoolGroup(name=name, trust_domain=domain, level=level, cot=(level == 3))
        if testing:
            name = f"{domain}-t"
            result[name] = PoolGroup(name=name, trust_domain=domain, level="t", cot=False)
    return result


def load_pool_groups_from_file(path="pool-groups.yml"):
    with open(path) as f:
        config = yaml.safe_load(f)
    return load_pool_groups(config)
