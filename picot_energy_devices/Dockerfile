ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20
FROM ${BUILD_FROM}

ARG BUILD_VERSION

RUN apk add --no-cache git \
    && echo "Building PicoT Energy Devices ${BUILD_VERSION}" \
    && git clone --depth 1 --branch main \
      https://github.com/Brons1981/PicoT-HEMS.git /tmp/picot-src \
    && cp -R /tmp/picot-src/src/picot_energy_devices /opt/picot_energy_devices \
    && rm -rf /tmp/picot-src \
    && apk del git

ENV PYTHONPATH=/opt

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
