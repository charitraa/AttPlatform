#!/bin/sh
# Development entrypoint: apply migrations, then run the given command.
set -e
python manage.py migrate --noinput
exec "$@"
