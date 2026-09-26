#!/usr/bin/env bash
# Entrypoint for the meridian-backend container:
#   1. wait for Postgres to accept connections
#   2. run Alembic migrations (idempotent: `upgrade head` is a no-op if already current)
#   3. exec the real command (uvicorn by default, or whatever CMD/`docker compose run` supplies)
set -euo pipefail

echo "[entrypoint] waiting for postgres..."
python <<'PY'
import os
import sys
import time

import psycopg

url = os.environ.get("DATABASE_URL", "")
# The app talks to Postgres via SQLAlchemy's asyncpg driver; psycopg (used only for this
# readiness probe) needs a plain postgresql:// URL.
sync_url = url.replace("postgresql+asyncpg://", "postgresql://")

timeout_seconds = float(os.environ.get("DB_WAIT_TIMEOUT_SECONDS", "60"))
deadline = time.monotonic() + timeout_seconds
last_err: Exception | None = None

while time.monotonic() < deadline:
    try:
        with psycopg.connect(sync_url, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        print("[entrypoint] postgres is ready", flush=True)
        break
    except Exception as exc:  # noqa: BLE001 - broad on purpose, this is a retry loop
        last_err = exc
        time.sleep(1)
else:
    print(f"[entrypoint] postgres did not become ready within {timeout_seconds}s: {last_err}", file=sys.stderr)
    sys.exit(1)
PY

# The worker shares this image and entrypoint but sets RUN_MIGRATIONS=0: two containers running
# `alembic upgrade head` against one database at the same time race on the version table. The API
# owns the schema; the worker waits for it to exist instead.
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "[entrypoint] running database migrations (alembic upgrade head)..."
  alembic upgrade head
else
  echo "[entrypoint] skipping migrations (RUN_MIGRATIONS=0); waiting for the schema instead"
  python <<'PY'
import os
import sys
import time

import psycopg

sync_url = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
deadline = time.monotonic() + float(os.environ.get("SCHEMA_WAIT_TIMEOUT_SECONDS", "120"))
while time.monotonic() < deadline:
    try:
        with psycopg.connect(sync_url, connect_timeout=3) as conn:
            row = conn.execute("select to_regclass('public.research_sessions')").fetchone()
            if row and row[0]:
                print("[entrypoint] schema is present")
                sys.exit(0)
    except Exception as exc:
        print(f"[entrypoint] waiting for schema: {exc}")
    time.sleep(2)
print("[entrypoint] schema did not appear in time", file=sys.stderr)
sys.exit(1)
PY
fi

echo "[entrypoint] starting: $*"
exec "$@"
