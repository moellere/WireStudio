# syntax=docker/dockerfile:1.7
#
# Single-image deployment for wirestudio.
#
# Two stages:
#   1. web-builder: Node + Vite, produces /web/dist with the SPA bundle.
#   2. runtime:     Python slim, installs the studio package + ships the
#                   built bundle. uvicorn serves the API under /api/* and
#                   the bundle at / via wirestudio.api.serve.
#
# Run:
#   docker run --rm -p 8765:8765 \
#     -e ANTHROPIC_API_KEY=sk-ant-... \
#     -v wirestudio-data:/data \
#     ghcr.io/moellere/wirestudio:latest
#
# Persistence: /data holds sessions/ + designs/. The container creates
# both subdirs on first launch; mount a named volume or host path here.
#
# Secrets (all optional): ANTHROPIC_API_KEY, FLEET_URL, FLEET_TOKEN,
# THINGIVERSE_API_KEY. Pass at runtime via -e or --env-file; never bake
# them into the image.
#
# LoRaWAN compile worker (optional, off by default): build with
#   docker build --build-arg WITH_LORAWAN=true -t wirestudio:lorawan .
# to add PlatformIO + the lorawan extra and pre-warm the espressif32
# toolchain into the image so the worker builds firmware offline in-pod.
# The default image stays slim (no PlatformIO, no ~1.5GB toolchain).

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
# The bundled library/, schema/, and examples/ live inside
# wirestudio/ as package-data, so a single COPY of the package
# picks them up.
COPY pyproject.toml ./
COPY wirestudio/ ./wirestudio/
COPY README.md ./

RUN pip install --no-cache-dir .

# Drop the built SPA into a stable path. WIRESTUDIO_STATIC_DIR points
# uvicorn at it through wirestudio.api.serve.
COPY --from=web-builder /web/dist /app/web-dist

# Persistence root. sessions/ + designs/ live under here so a single
# `-v <volume>:/data` survives upgrades.
RUN mkdir -p /data/sessions /data/designs && \
    useradd -m -s /bin/bash appuser && \
    chown -R appuser:appuser /app /data

# Optional LoRaWAN compile worker. When WITH_LORAWAN=true, install PlatformIO +
# the lorawan extra and pre-compile every radio board so the espressif32
# platform, toolchain, framework, and libraries are baked into a shared core
# dir -- the first in-pod build is then just the app sources (~1-2 min), and
# the pod is offline-capable. No-op (and no toolchain weight) when false.
ARG WITH_LORAWAN=false
ENV PLATFORMIO_CORE_DIR=/opt/pio
RUN <<'EOF'
set -eu
if [ "$WITH_LORAWAN" = "true" ]; then
    pip install --no-cache-dir platformio ".[lorawan]"
    mkdir -p "$PLATFORMIO_CORE_DIR"
    python -c "from wirestudio.library import default_library; from wirestudio.model import Design; from wirestudio.targets import get_target; from wirestudio.targets.lorawan.compile import compile_firmware; lib=default_library(); [compile_firmware(Design(schema_version='0.1', id='prewarm-'+b, name=b, target='lorawan', lorawan={}, board={'library_id': b, 'mcu': 'esp32'}, power={'supply':'usb','rail_voltage_v':3.3}), lib, use_cache=False) for b in get_target('lorawan').board_ids(lib)]"
    chown -R appuser:appuser "$PLATFORMIO_CORE_DIR"
fi
EOF

ENV PYTHONUNBUFFERED=1 \
    WIRESTUDIO_STATIC_DIR=/app/web-dist \
    SESSIONS_DIR=/data/sessions \
    DESIGNS_DIR=/data/designs \
    WIRESTUDIO_FW_CACHE=/data/firmware-cache

EXPOSE 8765
VOLUME ["/data"]

USER appuser

# tini reaps zombies + forwards SIGTERM cleanly so docker stop is fast.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "wirestudio.api", "--host", "0.0.0.0", "--port", "8765", "--static-dir", "/app/web-dist"]
