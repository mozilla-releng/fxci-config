"""
Temporary script to import docker-worker image identifiers from the
docker-worker releases on github.

To use: run this script, and append whatever bottom portion of the output represents
new images to worker-images.yml.
"""

import yaml
import requests
from collections import OrderedDict


def get_releases():
    res = requests.get(
        "https://api.github.com/repos/taskcluster/docker-worker/releases"
    )
    return res.json()


def main():
    images = OrderedDict()
    for rel in sorted(get_releases(), key=lambda r: r["name"]):
        name = rel["name"]
        for asset in rel["assets"]:
            if asset["name"] == "docker-worker-amis.json":
                break
        else:
            continue  # no data for this one
        amis = requests.get(asset["browser_download_url"]).json()
        for variety, variety_amis in amis.items():
            for region, ami in variety_amis.items():
                images.setdefault(f"docker-worker-{name}-{variety}", {}).setdefault(
                    "ec2", {}
                )[region] = ami

    print(yaml.dump(images, default_flow_style=False))


def represent_ordereddict(dumper, data):
    value = []

    for item_key, item_value in data.items():
        node_key = dumper.represent_data(item_key)
        node_value = dumper.represent_data(item_value)

        value.append((node_key, node_value))

    return yaml.nodes.MappingNode("tag:yaml.org,2002:map", value)


yaml.add_representer(OrderedDict, represent_ordereddict)


main()
