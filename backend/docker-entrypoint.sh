#!/bin/sh
set -e
case "$1" in
  api)
    alembic upgrade head
    exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 \
      --workers "${WEB_CONCURRENCY:-2}" --timeout 300 --graceful-timeout 30 --keep-alive 75 --access-logfile -
    ;;
  worker)
    exec arq app.workers.main.WorkerSettings
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  *)
    exec "$@"
    ;;
esac
