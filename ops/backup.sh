#!/bin/sh
# Kruvim backups: a PostgreSQL dump and an archive of uploaded files, every INTERVAL_HOURS, kept KEEP_DAYS days.
# Runs as the `backup` service in docker-compose.yml. Copy /backups off the server too (see docs/DEPLOYMENT.md).
set -eu
INTERVAL_HOURS="${INTERVAL_HOURS:-24}"
KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p /backups

while true; do
  stamp="$(date -u +%Y%m%d-%H%M%S)"
  echo "backup $stamp: database"
  if pg_dump -h postgres -U kruvim -d kruvim -Fc -f "/backups/db-$stamp.dump.partial"; then
    mv "/backups/db-$stamp.dump.partial" "/backups/db-$stamp.dump"
  else
    echo "backup $stamp: DATABASE DUMP FAILED" >&2
    rm -f "/backups/db-$stamp.dump.partial"
  fi
  if [ -d /data/objects ]; then
    echo "backup $stamp: uploaded files"
    tar -czf "/backups/files-$stamp.tar.gz.partial" -C /data objects && mv "/backups/files-$stamp.tar.gz.partial" "/backups/files-$stamp.tar.gz" \
      || { echo "backup $stamp: FILE ARCHIVE FAILED" >&2; rm -f "/backups/files-$stamp.tar.gz.partial"; }
  fi
  find /backups -type f \( -name 'db-*.dump' -o -name 'files-*.tar.gz' \) -mtime +"$KEEP_DAYS" -print -delete
  date -u +%Y-%m-%dT%H:%M:%SZ > /backups/last-run
  sleep "$((INTERVAL_HOURS * 3600))"
done
