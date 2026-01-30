FROM ubuntu:latest

ENV DEBIAN_FRONTEND=noninteractive
ENV TASKCLUSTER_ROOT_URL=https://firefox-ci-tc.services.mozilla.com/

RUN apt update && \
    apt install -y software-properties-common curl git

RUN add-apt-repository ppa:deadsnakes/ppa && \
    apt update && \
    apt install -y python3.11 python3.11-venv python3.11-dev

RUN curl -sS https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \
    python3.11 get-pip.py && \
    rm get-pip.py

WORKDIR /home/fxci-config

RUN mkdir -p /home/fxci-config/requirements

COPY requirements/*.txt /home/fxci-config/requirements/

RUN python3.11 -m pip install -r /home/fxci-config/requirements/test.txt

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["entrypoint.sh"]
