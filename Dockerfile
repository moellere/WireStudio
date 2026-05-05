# syntax=docker/dockerfile:1.7
#
# Single-image deployment for esphome-studio.
#
# Two stages:
#   1. web-builder: Node + Vite, produces /web/dist with the SPA bundle.
#   2. runtime:     Python slim, installs the studio package + ships the
#                   built bundle. uvicorn serves the API under /api/* and
#                   the bundle at / via studio.api.serve.
#
# Run:
#   docker run --rm -p 8765:8765 \
#     -e ANTHROPIC_API_KEY=sk-ant-... \
#     -v studio-data:/data \
#     ghcr.io/moellere/esphome-studio:latest
#
# Persistence: /data holds sessions/ + designs/. The container creates
# both subdirs on first launch; mount a named volume or host path here.
#
# Secrets (all optional): ANTHROPIC_API_KEY, FLEET_URL, FLEET_TOKEN,
# THINGIVERSE_API_KEY. Pass at runtime via -e or --env-file; never bake
# them into the image.

# ---------------------------------------------------------------------------
# Stage 1: build the SPA bundle.
# ---------------------------------------------------------------------------
FROM node:20-alpine AS web-builder
WORKDIR /web

# Cache npm install separately from sources -- a code-only change
# shouldn't bust the dep layer.
COPY web/package.json web/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY web/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: runtime.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Bare-minimum system layer: a CA bundle (httpx -> Anthropic / addon /
# Thingiverse) and tini for clean signal handling.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the studio package and its runtime deps. We copy only the
# dependency manifest first so the install layer caches across most
# code edits.
COPY pyproject.toml ./
COPY studio/ ./studio/
COPY library/ ./library/
COPY schema/ ./schema/
COPY examples/ ./examples/
COPY README.md ./

RUN pip install --no-cache-dir .

# Drop the built SPA into a stable path. STUDIO_STATIC_DIR points
# uvicorn at it through studio.api.serve.
COPY --from=web-builder /web/dist /app/web-dist

# Persistence root. sessions/ + designs/ live under here so a single
# `-v <volume>:/data` survives upgrades.
RUN mkdir -p /data/sessions /data/designs

ENV PYTHONUNBUFFERED=1 \
    STUDIO_STATIC_DIR=/app/web-dist \
    SESSIONS_DIR=/data/sessions \
    DESIGNS_DIR=/data/designs

EXPOSE 8765
VOLUME ["/data"]

# tini reaps zombies + forwards SIGTERM cleanly so docker stop is fast.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "studio.api", "--host", "0.0.0.0", "--port", "8765", "--static-dir", "/app/web-dist"]
