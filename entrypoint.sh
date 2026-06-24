#!/bin/bash

python3.11 -m pip install --root-user-action=ignore -e .

ci-admin "$@"
