# Deployment

[← docs index](index.md)

A single multi-arch Docker image (`linux/amd64` + `linux/arm64`) —
FastAPI serves the API and the built SPA from one process.

## Docker (single-image deployment)

```sh
docker run --rm -p 8765:8765 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v wirestudio-data:/data \
  ghcr.io/moellere/wirestudio:v0.12.0
```

Open <http://localhost:8765>. The image bundles the FastAPI server +
the built web UI in one process; `/api/*` is the JSON API, `/` is the
SPA. `/data` holds the agent's session log + saved designs across
upgrades.

Available tags:

| Tag | What it tracks |
|---|---|
| `:0.12.0` / `:0.12` / `:latest` | the v0.12.0 release |
| `:main` | latest commit on `main` (rolling) |
| `:dev` | latest commit on `dev` (rolling, pre-release) |
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

## ArgoCD: side-by-side prod + dev

Two Argo apps off one source tree, so a stable prod and a rolling dev
run in their own namespaces:

| App | Tracks | Image | Moves when |
|---|---|---|---|
| `wirestudio-prod` | branch `main`, path `deploy/overlays/prod` | pinned `:0.12.0` | you bump `newTag` in git |
| `wirestudio-dev` | branch `dev`, path `deploy/overlays/dev` | rolling `:sha-<short>` | every `dev` merge (CI commits the bump) |

```sh
kubectl apply -f deploy/argocd/wirestudio-prod.yaml
kubectl apply -f deploy/argocd/wirestudio-dev.yaml
```

How the image tag gets into git (no extra controller — pure GitOps):

- **dev** rolls itself. On every push to `dev`, the `docker` workflow's
  `bump-dev` job rewrites `deploy/overlays/dev/kustomization.yaml`'s
  `newTag` to the just-built `sha-<short>` and commits it back to `dev`
  (with `[skip ci]`). ArgoCD's automated sync deploys it.
- **prod** is promoted by hand. On release, bump `newTag` in
  `deploy/overlays/prod/kustomization.yaml` to the new version — do it in
  the `dev → main` release PR alongside `wirestudio/__init__.py` and
  `CHANGELOG.md`. ArgoCD rolls it out; rollback is a one-commit revert.

Each overlay sets its own namespace, so the two apps get independent
PVCs and never share `/data`.

> Branch protection note: the `bump-dev` job pushes to `dev` as
> `github-actions[bot]`. If you protect `dev`, add that bot to the
> "allow to bypass" list (or keep `dev` protection to required status
> checks on PRs only). Protect `main` strictly — PRs + green checks, no
> direct pushes — since releases land there via PR.

## nginx-front compose recipe

For an HTTP/2 + brotli front with independently-scaled API workers,
[`deploy/README.md`](../deploy/README.md) documents an opt-in
two-service docker-compose layout with `deploy/nginx.conf`.
