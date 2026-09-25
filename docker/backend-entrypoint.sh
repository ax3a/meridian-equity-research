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

echo "[entrypoint] running database migrations (alembic upgrade head)..."
alembic upgrade head

echo "[entrypoint] starting: $*"
exec "$@"
