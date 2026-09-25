# syntax=docker/dockerfile:1
#
# Meridian frontend image (Next.js 15 production server, standalone output).
#
# Build context MUST be the repository root, e.g.:
#   docker build -f docker/frontend.Dockerfile -t meridian-frontend .
# (docker-compose.yml at the repo root is already wired up this way.)
#
# Requires `output: "standalone"` in frontend/next.config.ts (already set).

################################################################################
# Stage: deps — install node_modules, cached on the lockfile only.
################################################################################
FROM node:20-slim AS deps

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

################################################################################
# Stage: builder — production build, produces .next/standalone.
################################################################################
FROM node:20-slim AS builder

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ .

RUN npm run build

################################################################################
# Stage: runner — minimal runtime image, non-root, just the standalone server.
################################################################################
FROM node:20-slim AS runner

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 nextjs \
    && useradd --uid 1000 --gid nextjs --shell /usr/sbin/nologin --create-home nextjs

WORKDIR /app

# Standalone output already contains a pruned node_modules with only what server.js needs.
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nextjs /app/public ./public

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=5 \
    CMD curl -fsS http://localhost:3000/ || exit 1

CMD ["node", "server.js"]
