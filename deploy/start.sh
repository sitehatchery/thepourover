#!/bin/sh
# Container start-up: prepare the database, create the first user if asked, load the sample data once, then run
# uvicorn and Nginx. If either process exits, the container exits so the platform restarts it.
set -eu

cd /srv/app/backend

# A platform volume mounted at /data starts out owned by root.
chown -R cdp /data

# Migrations and reference data (idempotent).
su cdp -s /bin/sh -c "python -m app.cli init-db"

# First sign-in: CDP_INITIAL_USER + CDP_INITIAL_PASSWORD create (or reset) that user on start-up.
if [ -n "${CDP_INITIAL_USER:-}" ] && [ -n "${CDP_INITIAL_PASSWORD:-}" ]; then
    su cdp -s /bin/sh -c "python -m app.cli create-user \"$CDP_INITIAL_USER\" --admin" >/dev/null
    echo "Ensured user $CDP_INITIAL_USER exists"
fi

# Load the sample data the first time the database is empty, so a fresh deploy has something to show.
if [ "${CDP_IMPORT_ON_FIRST_START:-true}" = "true" ] && [ ! -f /data/.first-import-done ]; then
    su cdp -s /bin/sh -c "python -m app.cli import" && touch /data/.first-import-done
fi

envsubst '${PORT}' < /etc/nginx/templates/cdp.conf.template > /etc/nginx/conf.d/cdp.conf

# Nginx is the only way in, so the forwarded client address it passes on is trusted. Uvicorn's access log is
# off because it prints query strings (which can hold emails); the app logs each request itself without them.
su cdp -s /bin/sh -c "exec uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips='*' --no-access-log" &
API_PID=$!
nginx -g 'daemon off;' &
NGINX_PID=$!

# Exit as soon as either one stops.
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$NGINX_PID" 2>/dev/null; do
    sleep 2
done
echo "A process exited; stopping container" >&2
kill "$API_PID" "$NGINX_PID" 2>/dev/null || true
exit 1
