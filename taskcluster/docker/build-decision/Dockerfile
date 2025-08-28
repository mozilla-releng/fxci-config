# %ARG PYTHON_VERSION
# %ARG UV_VERSION
FROM ghcr.io/astral-sh/uv:$UV_VERSION-python$PYTHON_VERSION-bookworm-slim AS builder
LABEL maintainer="Mozilla Release Engineering <release+build-decision@mozilla.com>"
WORKDIR /build

# %include build-decision/README.txt
# %include build-decision/pyproject.toml
# %include build-decision/src
# %include README.md
# %include uv.lock
# %include pyproject.toml
COPY topsrcdir/ /build

RUN ["uv", "sync", "--package=build-decision", "--no-dev", "--frozen"]

FROM python:$PYTHON_VERSION-slim
USER nobody
WORKDIR /build
COPY --from=builder /build /build

ENTRYPOINT ["/build/.venv/bin/build-decision"]
