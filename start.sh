#!/usr/bin/env sh
# Production start command for Render / any Linux host.
# Migrations are idempotent; rerunning this on every deploy is safe.
set -e

flask --app wsgi db upgrade

# Create the first administrator once, if credentials are supplied. The task is
# a no-op when the user already exists. Remove ADMIN_PASSWORD afterwards.
if [ -n "$ADMIN_EMAIL" ] && [ -n "$ADMIN_PASSWORD" ]; then
  flask --app wsgi bootstrap-admin
fi

exec gunicorn \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_WORKERS:-2}" \
  --threads "${WEB_THREADS:-4}" \
  --timeout "${WEB_TIMEOUT:-60}" \
  --access-logfile - \
  wsgi:app
