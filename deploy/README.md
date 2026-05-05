# Deployment recipes

The studio's published image is **single-process by default** — FastAPI
serves the API at `/api/*` and the SPA bundle at `/`. For most
self-hosters that's exactly what you want:

```sh
docker run --rm -p 8765:8765 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v studio-data:/data \
  ghcr.io/moellere/esphome-studio:latest
```

Open <http://localhost:8765>. Done.

## When to bother with the two-service compose

The `docker-compose.yml` in this directory adds an **nginx** in front
of the studio API. You probably don't need it unless one of these is
true:

- You serve multiple users at once and want nginx's `sendfile` /
  cache headers / brotli on top of the static bundle.
- You want HTTPS / a domain on top of the studio with a cert that
  isn't trivially exposed via a reverse proxy you already run.
- You run more than one studio replica behind a load balancer and want
  a known-good static-file frontend.

The compose stack mirrors the dev-time Vite proxy: nginx serves the
SPA bundle and proxies `/api/*` to the studio container after stripping
the prefix. The studio container runs in **API-only mode** (we set
`STUDIO_STATIC_DIR=` to disable the built-in static server) so we
don't double-serve the bundle.

```sh
cd deploy
# (optional) set ANTHROPIC_API_KEY=, FLEET_URL=, etc. in .env
docker compose pull
docker compose up -d
# UI now at http://localhost:8080/
```

## Architecture cheatsheet

| Concern | Single image (default) | Two-service compose |
|---|---|---|
| Containers | 1 | 2 + a one-shot copier |
| Static-file server | uvicorn + FastAPI `StaticFiles` | nginx 1.27 |
| API URL | `:8765/api/*` | `:8080/api/*` (proxied) |
| SPA URL | `:8765/` | `:8080/` |
| Persistence | `-v studio-data:/data` | `studio-data` named volume |

## Kubernetes

`k8s.yaml` is a minimal manifest covering the single-image pattern:
one Deployment, a 1 Gi PVC mounted at `/data`, a ClusterIP Service
on `:80 -> :8765`. Optional `studio-secrets` for the four feature-
gating env vars (none required to boot).

```sh
kubectl apply -f deploy/k8s.yaml
# Out-of-band, with real values (all keys optional):
kubectl create secret generic studio-secrets \
  --from-literal=anthropic-api-key=sk-ant-... \
  --from-literal=fleet-url=http://homeassistant.local:8765 \
  --from-literal=fleet-token=xxx \
  --from-literal=thingiverse-api-key=xxx
```

**Constraints to be aware of**:

- **Single replica only.** The studio's persistence (sessions JSONL +
  saved designs as JSON files) is file-on-disk and not safe across
  multiple writers. The Deployment uses `strategy: Recreate` so the
  old pod releases the PVC before the new one mounts it. Don't set
  `replicas > 1` until that state moves to a multi-writer-safe
  backend.
- **Liveness / readiness** both probe `/api/health`, which is cheap
  and unauthenticated.
- **No Ingress in the manifest.** Ingress controllers (nginx,
  traefik, cilium, gateway-api) vary too much for a default. A
  commented nginx-ingress example sits at the bottom of `k8s.yaml`
  with the two annotations that matter for the SSE build-log relay
  (`proxy-buffering: off` + a long `proxy-read-timeout`).
- **PSS / non-root.** The image runs as a non-root `appuser` (uid 1000),
  and the manifest's `securityContext` pins `runAsNonRoot: true` +
  `allowPrivilegeEscalation: false`, so it satisfies the Restricted
  Pod Security Standard out of the box. Existing /data volumes from
  pre-non-root runs may need a one-time `chown -R 1000:1000` if you
  upgrade across that boundary.

## Persistence + secrets

Both layouts mount `/data` into the studio container with two
sub-directories:

- `/data/sessions` — agent conversation history (one JSONL per session).
- `/data/designs` — saved-design store backing the UI's **Saved** tab.

Secrets are env vars and never baked into the image:

| Env var | What it gates |
|---|---|
| `ANTHROPIC_API_KEY` | the agent (`/agent/*` endpoints + the chat sidebar) |
| `FLEET_URL` + `FLEET_TOKEN` | distributed-esphome push (`/fleet/*`) |
| `THINGIVERSE_API_KEY` | enclosure search (`/enclosure/search`) |

## Updates

```sh
# Single image:
docker pull ghcr.io/moellere/esphome-studio:latest
docker stop studio && docker rm studio
docker run ...

# Two-service:
cd deploy
docker compose pull
docker compose up -d
```

The persistence volume survives across image pulls, so saved designs +
agent sessions carry over.
