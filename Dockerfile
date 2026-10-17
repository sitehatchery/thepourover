# Production image: Nginx serves the React build and proxies /app and /webhooks to FastAPI (uvicorn).
# Data (SQLite database, import reports) lives in /data, which should be a persistent volume.

# ---- 1. Build the React app --------------------------------------------------------------------------
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. Runtime: Python API + Nginx ---------------------------------------------------------------------
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx gettext-base tini \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default

WORKDIR /srv/app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY data/sample/ data/sample/
COPY --from=web /web/dist/ /srv/web/
COPY deploy/nginx/cdp.conf.template /etc/nginx/templates/cdp.conf.template
COPY deploy/nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY deploy/start.sh /usr/local/bin/start.sh
RUN sed -i 's/\r$//' /usr/local/bin/start.sh /etc/nginx/templates/cdp.conf.template /etc/nginx/snippets/security-headers.conf \
    && chmod +x /usr/local/bin/start.sh \
    && useradd --system --home /srv/app cdp \
    && mkdir -p /data && chown cdp /data

ENV CDP_DATA_DIR=/data \
    CDP_IMPORT_SOURCE_DIR=/srv/app/data/sample \
    CDP_COOKIE_SECURE=true \
    PYTHONUNBUFFERED=1 \
    PORT=8080

EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/usr/local/bin/start.sh"]
