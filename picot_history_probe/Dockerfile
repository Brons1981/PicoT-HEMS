FROM ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20

ARG BUILD_VERSION=0.2.0
ARG BUILD_ARCH=amd64
LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}"

ENV PYTHONPATH=/opt/probe/runtime \
    PYTHONDONTWRITEBYTECODE=1
COPY runtime /opt/probe/runtime
COPY probe.py large_probe.py source-manifest.json /opt/probe/
# One foreground Python process; no s6 daemon or restart loop.
ENTRYPOINT []
CMD ["python3", "-u", "/opt/probe/large_probe.py", "--scratch-parent", "/data"]
