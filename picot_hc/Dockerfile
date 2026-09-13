FROM python:3.12-alpine
RUN apk add --no-cache tzdata \
    && python -c "from zoneinfo import ZoneInfo; ZoneInfo('Europe/Amsterdam')"
WORKDIR /app
COPY picot_hc /app/picot_hc
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "picot_hc"]
