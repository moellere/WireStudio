# Deployment

[← docs index](index.md)

A single multi-arch Docker image (`linux/amd64` + `linux/arm64`) —
FastAPI serves the API and the built SPA from one process.

## Docker (single-image deployment)

```sh
docker run --rm -p 8765:8765 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v wirestudio-data:/data \
  ghcr.io/moellere/wirestudio:v0.17.1
```

Open <http://localhost:8765>. The image bundles the FastAPI server +
the built web UI in one process; `/api/*` is the JSON API, `/` is the
SPA. `/data` holds the agent's session log + saved designs across
upgrades.

Available tags:

| Tag | What it tracks |
|---|---|
| `:0.17.1` / `:0.17` / `:latest` | the v0.17.1 release |
| `:main` | latest commit on `main` (rolling) |
| `:dev` | latest commit on `dev` (rolling, pre-release) |
| `:sha-<short>` | a specific commit |
| `:<tag>-lorawan` (e.g. `:dev-lorawan`) | same image **plus** the LoRaWAN compile worker (PlatformIO baked in) — see below |

All feature-gating env vars are optional — the studio runs without any
of them, just with the corresponding feature turned off. See
[Integrations](integrations.md) for what each one enables:

| Env var | What it gates |
|---|---|
| `ANTHROPIC_API_KEY` | the agent (`/agent/*` endpoints + the chat sidebar) |
| `FLEET_URL` + `FLEET_TOKEN` | fleet-for-esphome push (`/fleet/*`) |
| `THINGIVERSE_API_KEY` | enclosure search (`/enclosure/search`) |
| `WIRESTUDIO_MCP_TOKEN` | bearer token for the `/mcp` endpoint (auto-generated if unset) |
| `CHIRPSTACK_API_URL` + `CHIRPSTACK_API_TOKEN` | LoRaWAN device provisioning against ChirpStack (`/lorawan/provision`, `/lorawan/provision-esphome`) |

### LoRaWAN compile worker

The default image is lean — it has no PlatformIO toolchain, so the
**standalone Arduino LoRaWAN target's** `/lorawan/compile` endpoint
returns "PlatformIO not found" and the **Flash LoRaWAN firmware** flow
can't build. To run that feature in a deployment, use the **`-lorawan`
image variant** (or build it yourself:
`docker build --build-arg WITH_LORAWAN=true -t wirestudio:lorawan .`). It
adds PlatformIO + the `[lorawan]` extra and pre-compiles every radio
board so the espressif32 toolchain is already warm — a bigger image, but
`/lorawan/compile` returns a cache hit on first use.

The **external-component LoRaWAN path** (`Design.target: "esphome"` +
`lorawan.payload`) doesn't need the `-lorawan` image variant — the
LoRaWAN device's firmware is built by ESPHome inside fleet-for-esphome
the same way every other device is, so the studio image stays lean. The
default image is enough; only the `/lorawan/provision-esphome` endpoint
needs ChirpStack credentials.

Pair either path with `CHIRPSTACK_API_URL` + `CHIRPSTACK_API_TOKEN` (see
[Integrations](integrations.md#lorawan--chirpstack)). WebSerial flashing
happens in the user's browser, so the device only needs to reach *their*
machine, not the server.

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
| `wirestudio-prod` | branch `main`, path `deploy/overlays/prod` | pinned `:0.17.1` | a release tag opens a `newTag` bump PR (you merge it) |
| `wirestudio-dev` | branch `dev`, path `deploy/overlays/dev` | rolling `:sha-<short>-lorawan` | every `dev` merge (CI commits the bump) |

```sh
kubectl apply -f deploy/argocd/wirestudio-prod.yaml
kubectl apply -f deploy/argocd/wirestudio-dev.yaml
```

How the image tag gets into git (no extra controller — pure GitOps).
All three bumps are jobs in the `docker` workflow:

- **dev** rolls itself. On every push to `dev`, the `bump-dev` job
  rewrites `deploy/overlays/dev/kustomization.yaml`'s `newTag` to the
  just-built `sha-<short>-lorawan` and commits it back to `dev` (with
  `[skip ci]`). ArgoCD's automated sync deploys it.
- **prod** is bumped on the release tag. When a `v*` tag is pushed,
  `bump-prod` rewrites `deploy/overlays/prod/kustomization.yaml`'s
  `newTag` to the bare semver and opens a PR against `main` (branch
  `deploy/prod-<version>`). `main` is protected — PR + required checks —
  so the job can't push directly; merging the PR rolls prod. ArgoCD
  rolls it out; rollback is a one-commit revert.
- **dev, on a release tag too.** `bump-dev-on-tag` points the dev
  overlay at the released `:<version>-lorawan` image so the dev cluster
  can briefly smoke-test the release build. It no-ops when no `dev`
  branch exists.

The release tag also drives `github-release`, which cuts the GitHub
Release from the matching `CHANGELOG.md` section.

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
