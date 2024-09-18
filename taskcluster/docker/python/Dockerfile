# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

# %ARG PYTHON_VERSION
FROM python:$PYTHON_VERSION
LABEL maintainer="Mozilla Release Engineering <release+fxci-config@mozilla.com>"

VOLUME /builds/worker/checkouts
VOLUME /builds/worker/.cache

# Add worker user
RUN mkdir -p /builds && \
    useradd -d /builds/worker -s /bin/bash -m worker && \
    mkdir /builds/worker/artifacts && \
    chown worker:worker /builds/worker/artifacts

# %include-run-task

RUN apt-get update && apt-get install -y --force-yes --no-install-recommends \
    mercurial

ENV SHELL=/bin/bash \
    HOME=/builds/worker \
    PATH=/builds/worker/.local/bin:$PATH

COPY --from=ghcr.io/astral-sh/uv:0.4.13 /uv /bin/uv

# Set a default command useful for debugging
CMD ["/bin/bash", "--login"]
