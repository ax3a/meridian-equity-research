# syntax=docker/dockerfile:1
#
# Meridian backend image (FastAPI app served by uvicorn).
#
# Build context MUST be the repository root, e.g.:
#   docker build -f docker/backend.Dockerfile -t meridian-backend .
# (docker-compose.yml at the repo root is already wired up this way.)

################################################################################
# Stage: builder — install Python dependencies into an isolated venv.
################################################################################
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# build-essential/libpq-dev: a couple of transitive deps (e.g. psycopg's non-binary fallback,
# lxml on platforms without a prebuilt wheel) may need to compile.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /build

# --- Dependency layer -------------------------------------------------------
# Install dependencies keyed only on pyproject.toml plus an empty package stub, so editing
# application source under backend/src does NOT invalidate this (slow) layer.
COPY backend/pyproject.toml ./pyproject.toml
RUN mkdir -p src/meridian \
    && touch src/meridian/__init__.py \
    && pip install --upgrade pip \
    && pip install ".[embeddings,otel]"

# --- Application layer -------------------------------------------------------
# Now bring in the real source and reinstall the package itself (fast: no deps to resolve).
COPY backend/src ./src
RUN pip install --no-deps ".[embeddings,otel]"

################################################################################
# Stage: runtime — small image with just the venv + source, running as non-root.
################################################################################
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"

# libpq5: runtime shared lib for psycopg; curl: used by the HEALTHCHECK below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 meridian \
    && useradd --uid 1000 --gid meridian --shell /usr/sbin/nologin --create-home --home-dir /home/meridian meridian

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app/backend

# alembic.ini's `script_location = src/meridian/db/migrations` is relative to the working
# directory, so the entrypoint runs `alembic upgrade head` from here.
COPY backend/alembic.ini ./alembic.ini
COPY backend/src ./src

# Recorded provider snapshots let the app run fully offline (DATA_MODE=snapshot/auto) with no
# network access and no API keys — see backend/scripts/record_snapshots.py.
COPY backend/snapshots ./snapshots

COPY docker/backend-entrypoint.sh /usr/local/bin/backend-entrypoint.sh

RUN chmod +x /usr/local/bin/backend-entrypoint.sh \
    && mkdir -p /app/backend/.models \
    && chown -R meridian:meridian /app /home/meridian

# `Settings.model_cache_dir` defaults to a path relative to the source tree, which does not exist for an
# installed package: in the image it resolved to /opt/venv/lib/python3.12/.models, which the non-root
# user cannot write. fastembed then failed to load and fell back to hashing embeddings -- a quieter and
# worse failure than crashing would have been, and one that only showed up in the worker's logs.
ENV MODEL_CACHE_DIR=/app/backend/.models

USER meridian

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["/usr/local/bin/backend-entrypoint.sh"]
CMD ["uvicorn", "meridian.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
