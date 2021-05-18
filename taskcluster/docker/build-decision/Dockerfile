# %ARG PYTHON_VERSION
FROM python:$PYTHON_VERSION-slim
MAINTAINER Tom Prince <mozilla@hocat.ca>

# %include build-decision/requirements/base.in
# %include build-decision/requirements/base.txt
# %include build-decision/setup.py
# %include build-decision/src
ADD topsrcdir/build-decision /setup/
RUN ["pip", "install", "-r", "/setup/requirements/base.txt"]
RUN ["pip", "install", "--no-deps", "/setup"]
RUN ["/bin/rm", "-rf", "/setup"]

USER nobody
ENTRYPOINT ["build-decision"]
