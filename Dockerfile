# syntax=docker/dockerfile:1

FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.14-slim@sha256:d3400aa122fa42cf0af0dbe8ec3091b047eac5c8f7e3539f7135e86d855dc015

WORKDIR /app
COPY bridge.py config.py db.py filters.py hermes_client.py incidents.py message_format.py notifications.py ntfy_publish.py query_parser.py raise_rules.py settings.py ui.py VERSION /app/
COPY integrations/ /app/integrations/
COPY --from=web /web/dist /app/web/dist

ENV INCIDENT_DIR=/data/incidents \
    HTTP_PORT=8000 \
    HEARTH_STATIC=/app/web/dist

EXPOSE 8000
VOLUME ["/data/incidents"]

CMD ["python3", "/app/bridge.py"]
