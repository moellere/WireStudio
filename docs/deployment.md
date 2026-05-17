# Deployment

[← docs index](index.md)

A single multi-arch Docker image (`linux/amd64` + `linux/arm64`) —
FastAPI serves the API and the built SPA from one process.

## Docker (single-image deployment)

```sh
docker run --rm -p 8765:8765 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v wirestudio-data:/data \
  ghcr.io/moellere/wirestudio:v0.10.0
```

Open <http://localhost:8765>. The image bundles the FastAPI server +
the built web UI in one process; `/api/*` is the JSON API, `/` is the
SPA. `/data` holds the agent's session log + saved designs across
upgrades.

Available tags:

| Tag | What it tracks |
|---|---|
| `:v0.10.0` / `:0.10.0` / `:0.10` / `:latest` | the v0.10.0 release |
| `:main` | latest commit on `main` (rolling) |
| `:sha-<short>` | a specific commit |

All feature-gating env vars are optional — the studio runs without any
of them, just with the corresponding feature turned off. See
[Integrations](integrations.md) for what each one enables:

| Env var | What it gates |
|---|---|
| `ANTHROPIC_API_KEY` | the agent (`/agent/*` endpoints + the chat sidebar) |
| `FLEET_URL` + `FLEET_TOKEN` | fleet-for-esphome push (`/fleet/*`) |
| `THINGIVERSE_API_KEY` | enclosure search (`/enclosure/search`) |
| `WIRESTUDIO_MCP_TOKEN` | bearer token for the `/mcp` endpoint (auto-generated if unset) |

## Kubernetes

A ready-to-apply manifest lives at [`deploy/k8s.yaml`](../deploy/k8s.yaml) —
one Deployment, a 1 Gi PVC mounted at `/data`, and a ClusterIP Service.
Single replica with the `Recreate` strategy: the studio's persistence
is file-on-disk and not multi-writer safe.

```sh
kubectl apply -f deploy/k8s.yaml
```

## nginx-front compose recipe

For an HTTP/2 + brotli front with independently-scaled API workers,
[`deploy/README.md`](../deploy/README.md) documents an opt-in
two-service docker-compose layout with `deploy/nginx.conf`.
