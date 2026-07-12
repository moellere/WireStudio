# Deployment

[← docs index](index.md)

A single multi-arch Docker image (`linux/amd64` + `linux/arm64`) —
FastAPI serves the API and the built SPA from one process.

## Docker (single-image deployment)

```sh
docker run --rm -p 8765:8765 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v wirestudio-data:/data \
  ghcr.io/moellere/wirestudio:0.18.0
```

Open <http://localhost:8765>. The image bundles the FastAPI server +
the built web UI in one process; `/api/*` is the JSON API, `/` is the
SPA. `/data` holds the agent's session log + saved designs across
upgrades.

Available tags:

| Tag | What it tracks |
|---|---|
| `:0.18.0` / `:0.18` / `:latest` | the v0.18.0 release |
| `:main` | latest commit on `main` (rolling) |
| `:sha-<short>` | a specific commit |
| `:<tag>-lorawan` (e.g. `:main-lorawan`, `:0.18.0-lorawan`) | same image **plus** the LoRaWAN compile worker (PlatformIO baked in) — see below |

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

## ArgoCD: side-by-side prod + staging

`deploy/argocd/` has two example `Application` manifests — a stable prod
app and a rolling staging app. Each layers a namespace + image tag over
the base manifest through a kustomize overlay (`deploy/overlays/{prod,dev}`),
so both run side by side from one source tree with independent PVCs.

| App | Overlay | Image | Upgrades when |
|---|---|---|---|
| `wirestudio-prod` | `deploy/overlays/prod` | pinned release, e.g. `:0.18.0` | the tag changes in git (bump by hand or via image-updater) |
| `wirestudio-dev` | `deploy/overlays/dev` | rolling `:main-lorawan` | image-updater digest-pins a new `main` build |

```sh
kubectl apply -f deploy/argocd/wirestudio-prod.yaml
kubectl apply -f deploy/argocd/wirestudio-dev.yaml
```

Both apps run `automated: { prune, selfHeal }`, so ArgoCD applies git
changes and reverts manual cluster edits on its own. Staging tracks the
`:main-lorawan` tag (the LoRaWAN worker variant, so the compile/flash
flow works on staging); prod pins an immutable release tag and stays
lean. Each overlay sets its own namespace, so the apps never share
`/data`.

### Keeping the image current

A kustomize `newTag` is static — ArgoCD only redeploys when that value
changes in git. Two ways to move it forward:

- **By hand.** Edit `newTag` in the overlay and commit; ArgoCD rolls it
  out. Explicit and auditable, and a rollback is a one-commit revert.
- **Automatically — [argocd-image-updater](https://argocd-image-updater.readthedocs.io/)
  (recommended).** Point it at `ghcr.io/moellere/wirestudio` and it
  writes the newest matching tag (with digest) back to git, so a pushed
  image deploys itself with no manual step. This is how the upstream
  cluster runs both apps:
  - **staging** tracks `:main-lorawan` with `updateStrategy: digest` —
    every merge to `main` redeploys.
  - **prod** follows the newest release with `updateStrategy: newest-build`
    and `allowTags: "regexp:^[0-9]+\.[0-9]+\.[0-9]+-lorawan$"` — a pushed
    `vX.Y.Z` tag rolls prod on its own.

  > The `regexp:` prefix on `allowTags` is required. A bare pattern is
  > treated as a literal tag name and silently matches nothing, so the
  > app never updates.

Pushing a `v*` tag builds + publishes the release image (the `docker`
workflow), publishes to PyPI, and cuts a GitHub Release from the matching
`CHANGELOG.md` section (the `release` workflow). Deployment itself is
decoupled from CI: the image lands in the registry, and whichever
mechanism above owns the tag picks it up.

> If image-updater does the git write-back, give its commit identity push
> access to the repo/branch it targets, and keep `main` protection to
> required checks on PRs (image-updater commits tag bumps directly).

## nginx-front compose recipe

For an HTTP/2 + brotli front with independently-scaled API workers,
[`deploy/README.md`](../deploy/README.md) documents an opt-in
two-service docker-compose layout with `deploy/nginx.conf`.
