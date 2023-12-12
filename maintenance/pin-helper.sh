#!/bin/bash
# This runs in docker to pin our requirements files.
set -e
SUFFIX=${SUFFIX:-txt}

pip install --upgrade pip
pip install pip-compile-multi

# XXX pip-tools 6.4.0 from pip-compile-multi 2.4.2 requires
#     pip>=21.2 without hashes, which breaks including hashes in test.txt >_<
#     add -s to allow for "unsafe" pinning, i.e. include `pip`
ARGS="-s -g base -g test"
if [ -f requirements/local.in ]; then
    ARGS="$ARGS -g local"
fi
pip-compile-multi -o "$SUFFIX" $ARGS
chmod 644 requirements/*.txt
