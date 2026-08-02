ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20
FROM ${BUILD_FROM}

RUN apk add --no-cache git \
    && python -m pip install --no-cache-dir \
      "git+https://github.com/Brons1981/PicoT-HEMS.git@main"

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
