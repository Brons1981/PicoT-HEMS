ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20
FROM ${BUILD_FROM}

ARG BUILD_VERSION

RUN apk add --no-cache git \
    && echo "Building PicoT HEMS ${BUILD_VERSION}" \
    && python -m pip install --no-cache-dir \
      "git+https://github.com/Brons1981/PicoT-HEMS.git@rebuild/canonical-pipeline"

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
