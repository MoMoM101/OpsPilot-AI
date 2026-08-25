#!/usr/bin/env bash
set -euo pipefail

drill_dir="$(mktemp -d)"
restore_database="opspilot_restore_drill"

cleanup() {
  docker run --rm --network host \
    -e PGPASSWORD="$OPSPILOT_POSTGRES_PASSWORD" \
    postgres:17-alpine \
    dropdb --if-exists --host 127.0.0.1 --username opspilot "$restore_database" \
    >/dev/null 2>&1 || true
  rm -rf -- "$drill_dir"
}
trap cleanup EXIT

docker run --rm --network host \
  -e PGPASSWORD="$OPSPILOT_POSTGRES_PASSWORD" \
  -v "$drill_dir:/backup" \
  postgres:17-alpine \
  pg_dump --host 127.0.0.1 --username opspilot --dbname opspilot \
  --format custom --no-owner --no-privileges --file /backup/opspilot.dump

docker run --rm --network host \
  -e PGPASSWORD="$OPSPILOT_POSTGRES_PASSWORD" \
  postgres:17-alpine \
  createdb --host 127.0.0.1 --username opspilot "$restore_database"

docker run --rm --network host \
  -e PGPASSWORD="$OPSPILOT_POSTGRES_PASSWORD" \
  -v "$drill_dir:/backup:ro" \
  postgres:17-alpine \
  pg_restore --host 127.0.0.1 --username opspilot --dbname "$restore_database" \
  --exit-on-error --no-owner --no-privileges /backup/opspilot.dump

source_head="$(docker run --rm --network host \
  -e PGPASSWORD="$OPSPILOT_POSTGRES_PASSWORD" \
  postgres:17-alpine \
  psql --host 127.0.0.1 --username opspilot --dbname opspilot \
  --tuples-only --no-align --command 'SELECT version_num FROM alembic_version;')"
restored_head="$(docker run --rm --network host \
  -e PGPASSWORD="$OPSPILOT_POSTGRES_PASSWORD" \
  postgres:17-alpine \
  psql --host 127.0.0.1 --username opspilot --dbname "$restore_database" \
  --tuples-only --no-align --command 'SELECT version_num FROM alembic_version;')"

test -n "$source_head"
test "$source_head" = "$restored_head"
