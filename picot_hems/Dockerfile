ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20
FROM ${BUILD_FROM}

ARG BUILD_VERSION

RUN apk add --no-cache git \
    && echo "Building PicoT HEMS ${BUILD_VERSION}" \
    && git clone --depth 1 --branch main \
      https://github.com/Brons1981/PicoT-HEMS.git /tmp/picot-src \
    && mkdir -p /opt/picot/picot \
    && cp -R /tmp/picot-src/src/picot/domain /opt/picot/picot/domain \
    && cp -R /tmp/picot-src/src/picot/v2 /opt/picot/picot/v2 \
    && touch /opt/picot/picot/__init__.py \
    && rm -rf /tmp/picot-src \
    && apk del git

ENV PYTHONPATH=/opt/picot

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
