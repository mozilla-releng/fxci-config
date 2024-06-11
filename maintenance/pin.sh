#!/usr/bin/env bash
# Pin all requirements.
#
# As of this writing, cloudops-jenkins uses an image based off of python:3.9
# to run ci-admin
#
# To test, after running maintenance/pin.sh:
#
#    docker pull gcr.io/moz-fx-cloudops-images-global/cloudops-infra-deploylib:2
#    docker run -it --mount type=bind,source="$(pwd)",target=/mnt gcr.io/moz-fx-cloudops-images-global/cloudops-infra-deploylib:2  bash
#    python -mvenv x
#    . x/bin/activate
#    pip install -r /mnt/requirements/local.txt


set -e
set -x

docker run --rm -ti -v $PWD:/src -w /src python:3.9 maintenance/pin-helper.sh
docker run --rm -ti -v $PWD:/src -w /src/build-decision python:3.11 ../maintenance/pin-helper.sh
