# ChirpStack LoRaWAN Setup — Reference for Project Development

Snapshot of the LoRaWAN stack as it stands after the May 2026 setup session.
This doc is a self-contained reference: hardware, network topology, every config
change, MQTT topic structure, and the operational properties to design around.

> Credentials are redacted to `<placeholders>`; supply the real values at deploy
> time from the environment / a secret store (see §11). Nothing secret is committed
> in this repo. Hostnames, IP addresses, gateway IDs, and DNS names in this doc
> are illustrative placeholders (`mygw`, `10.0.x.x`, `*.example.com`) -- swap in
> your own when adapting.

---

## 1. Physical / Hardware

| Component | Detail |
|---|---|
| Gateway hostname | `mygw` |
| Gateway IP | `10.0.0.10` (remote site, behind VPN) |
| Host | Raspberry Pi 4 Model B Rev 1.1, 4 GB RAM, armv7l |
| Concentrator | RAK2287 on RAK Pi Hat (SX1302 + dual SX1250) |
| Antenna | External 8 dBi, SMA via u.fl pigtail |
| GNSS | Onboard, `/dev/ttyAMA0`, locked |
| SPI | `/dev/spidev0.0` (CS0), reset on GPIO 17 |
| I²C | `/dev/i2c-1` (concentrator temp sensor) |
| Region / band | US915, sub-band 2 (`us915_1` in ChirpStack) — 903.9–905.3 MHz multi-SF + 904.6 MHz 500 kHz LoRa-Std |
| Gateway ID (from chip silicon) | `0000000000000000` (per-device; read from your gateway) |

Access: `ssh root@10.0.0.10` (key auth, no password).

---

## 2. Network Topology

Two separate sites connected over VPN:

```
┌── Gateway site (10.0.0.0/24) ────────┐    VPN    ┌── HA site (10.0.1.0/24) ────┐
│                                       │           │                              │
│  mygw (10.0.0.10)                │◄═════════►│  HAOS VM (10.0.1.10)       │
│   ├─ ChirpStack 4.17 (port 8080)      │           │   ├─ mosquitto (port 1883)   │
│   ├─ mosquitto (port 1883, local)     │           │   ├─ Home Assistant Core     │
│   ├─ chirpstack-concentratord-sx1302  │           │   ├─ HACS                    │
│   └─ chirpstack-mqtt-forwarder        │           │   └─ chirp custom_component  │
│                                       │           │                              │
└───────────────────────────────────────┘           └──────────────────────────────┘
```

Other reachable hosts you may need:
- `home.example.com:8123` — HA web UI
- `argo.example.com` — ArgoCD
- `auth.example.com` — SSO

---

## 3. Software Versions

| Package | Version | Source |
|---|---|---|
| ChirpStack Gateway OS | 4.11.0 | Latest release; bundled image, sysupgrade for next version |
| ChirpStack network server | 4.17.0 | Baked into the OS image; not via opkg feeds |
| chirpstack-concentratord-sx1302 | 4.7.0 | Baked into OS image |
| chirpstack-mqtt-forwarder | 4.5.1 | Baked into OS image |
| mosquitto (broker + clients) | 2.0.18 | OpenWrt 24.10.6 base feed |
| OpenWrt base | 24.10.6 (bcm27xx/bcm2709, arm_cortex-a7_neon-vfpv4) | upstream OpenWrt |
| chirp HA custom_component | latest from `github.com/modrisb/chirp` | Installed via HACS custom repository |

**Note:** ChirpStack packages are part of the firmware image, not opkg-managed. To
upgrade ChirpStack you wait for a Gateway OS release with a newer version and run
`sysupgrade` with the new image.

---

## 4. Final Architecture (after all session changes)

**Everything terminates on the Pi's local mosquitto. A mosquitto bridge handles the VPN.**

```
                              Pi (10.0.0.10)
   ┌──────────────────────────────────────────────────────────┐
   │                                                          │
   │  [RAK2287/SX1302] ──SPI──> [concentratord-sx1302]        │
   │                                  │                       │
   │                                  │ IPC (zeromq):         │
   │                                  │  /tmp/concentratord_event   │
   │                                  │  /tmp/concentratord_command │
   │                                  ▼                       │
   │                       [chirpstack-mqtt-forwarder]        │
   │                                  │                       │
   │                                  │ MQTT pub/sub          │
   │                                  ▼                       │
   │                       [mosquitto :1883]  ◄──┐            │
   │                         ▲     │             │            │
   │      gateway backend ───┘     │ integration │            │
   │      (sub)             ┌──────┘ (pub/sub)   │            │
   │                        ▼                    │            │
   │                   [chirpstack :8080]        │            │
   │                                             │            │
   │                                  bridge ────┘            │
   │                                  (out: events, state)    │
   │                                  (in:  commands)         │
   │                                  ┊  persistent queue     │
   │                                  ┊  /srv/mosquitto/      │
   └──────────────────────────────────┊───────────────────────┘
                                      ┊ VPN
                              HAOS VM (10.0.1.10)
   ┌──────────────────────────────────▼───────────────────────┐
   │  [mosquitto :1883] ──> [chirp custom_component]          │
   │                                  │                       │
   │                                  ▼                       │
   │                       [Home Assistant entities]          │
   └──────────────────────────────────────────────────────────┘
```

### Why this shape

1. **Gateway face is fully local on the Pi.** LoRaWAN works even when the VPN is down: uplinks get decrypted, MAC commands handled, OTAA joins processed, beacons emitted. Data accumulates in ChirpStack's SQLite.

2. **Mosquitto bridge handles the VPN crossing.** When VPN drops, events queue on disk and replay in order when it recovers. ChirpStack itself never talks across the VPN.

3. **Detection latency:** bridge keepalive is 30 s, so outage is noticed in ~45 s. During detection the in-flight QoS 1 publishes already have delivery guarantees from the broker.

### What happens during a VPN outage

| Subsystem | Behavior |
|---|---|
| LoRaWAN radio | Unaffected. Uplinks/downlinks/joins all work. |
| ChirpStack DB | Records everything as normal. |
| Local mosquitto | Queues integration events to `/srv/mosquitto/mosquitto.db`, capped at 100 000 messages. |
| HA chirp integration | Sees no new events until VPN recovers. |
| Recovery | Bridge auto-reconnects (`restart_timeout 5 30`), drains queue at QoS 1, state topic flips back to `1`. HA gets all the buffered events in order. |

Verified live: blackholed route to 10.0.1.10 → bridge state went `1→0` after ~45 s
→ 5 test messages queued → route restored → state `1` → messages drained to HA broker.

---

## 5. Config Files (all on the Pi)

All files have `.bak` siblings from the session.

### 5.1 `/etc/config/chirpstack-mqtt-forwarder` (UCI)

```
config global
        option enabled '1'

config mqtt
        option topic_prefix 'us915_1'
        option server 'tcp://127.0.0.1:1883'
        option qos '0'
        option client_id 'chirpstack'

config filters
```

No credentials — local mosquitto is anonymous.

### 5.2 `/etc/chirpstack/region_us915_1.toml` (gateway backend MQTT only)

Relevant section:

```toml
[regions.gateway.backend.mqtt]
  topic_prefix = "us915_1"
  share_name = "chirpstack"
  server = "tcp://localhost:1883"
  username = ""
  password = ""
```

`share_name` matters if you ever stand up a second ChirpStack on the same broker — they'd round-robin events. Change one of them.

### 5.3 `/etc/init.d/chirpstack` (network server config heredoc)

The `configuration()` function generates `/var/etc/chirpstack/chirpstack.toml` from a heredoc. Current relevant block:

```toml
[sqlite]
path="/srv/chirpstack/chirpstack.sqlite"

[gateway]
allow_unknown_gateways=true

[integration]
enabled = ["mqtt"]

[integration.mqtt]
json=true
server="tcp://127.0.0.1:1883/"

[network]
net_id="000000"
enabled_regions=["us915_1",]

[api]
secret="<chirpstack-api-secret>"   # gateway-side JWT signing secret; injected at provisioning, see §11
```

Integration MQTT is now local (no creds). The bridge ferries everything to HA.

### 5.4 `/etc/mosquitto/mosquitto.conf` (full file)

```conf
log_dest syslog
persistence true
persistence_location /srv/mosquitto/
autosave_interval 60
max_queued_messages 100000
queue_qos0_messages true

listener 1883
allow_anonymous true

# --- bridge to HA mosquitto over the VPN ---
connection ha_bridge
address 10.0.1.10:1883
remote_username chirpstack
remote_password <ha-mqtt-password>
remote_clientid mygw-bridge
local_clientid  mygw-bridge-local
cleansession false
start_type automatic
restart_timeout 5 30
keepalive_interval 30
notifications true
notification_topic gateway/mygw/bridge/state
try_private false
bridge_protocol_version mqttv311

# uplink events local -> remote
topic application/+/device/+/event/+ out 1 "" ""
# device state (online/last-seen) local -> remote
topic application/+/device/+/state/+ out 1 "" ""
# downlinks remote -> local
topic application/+/device/+/command/+ in 1 "" ""
# bridge connection state -> remote (for HA bridge-health sensor)
topic gateway/mygw/bridge/state out 1 "" ""
```

### 5.5 Disabled service

- `chirpstack-udp-forwarder` — stopped + disabled in UCI. Was pointed at 127.0.0.1:1700 with no listener (legacy default config); just spammed `PULL_DATA not acknowledged` every 10 s.

---

## 6. MQTT Topic Structure (the contract your project depends on)

All topics live on the HA mosquitto at `10.0.1.10:1883` (creds `chirpstack` / `<ha-mqtt-password>`, see §11) because the bridge ferries them.

### 6.1 Gateway-layer topics (`us915_1/...`)

These are **internal** between the forwarder and ChirpStack. They stay on the Pi's local broker and **do not cross the bridge**. You typically won't subscribe to these from a project — let ChirpStack consume them.

| Topic pattern | Direction | Payload |
|---|---|---|
| `us915_1/gateway/{gw_id}/event/up` | forwarder → chirpstack | protobuf gateway uplink |
| `us915_1/gateway/{gw_id}/event/stats` | forwarder → chirpstack | protobuf gateway stats (every 30 s) |
| `us915_1/gateway/{gw_id}/event/ack` | forwarder → chirpstack | downlink TX ack |
| `us915_1/gateway/{gw_id}/state/conn` | forwarder → chirpstack | retained connection state |
| `us915_1/gateway/{gw_id}/command/down` | chirpstack → forwarder | downlink to schedule |
| `us915_1/gateway/{gw_id}/command/config` | chirpstack → forwarder | gateway reconfiguration |

### 6.2 Application-layer topics (`application/...`) — **this is what your project uses**

ChirpStack publishes to / subscribes from these. They cross the bridge to HA's broker.

| Topic pattern | Direction | Payload (JSON when `json=true`) |
|---|---|---|
| `application/{app_id}/device/{dev_eui}/event/up` | chirpstack → consumers | decoded uplink: `deviceInfo`, `data` (base64), `object` (codec output), `rxInfo[]`, `txInfo` |
| `application/{app_id}/device/{dev_eui}/event/join` | chirpstack → consumers | OTAA join completed |
| `application/{app_id}/device/{dev_eui}/event/ack` | chirpstack → consumers | confirmed downlink ack |
| `application/{app_id}/device/{dev_eui}/event/txack` | chirpstack → consumers | downlink TX scheduled |
| `application/{app_id}/device/{dev_eui}/event/log` | chirpstack → consumers | downlink error / device log entry |
| `application/{app_id}/device/{dev_eui}/event/status` | chirpstack → consumers | DevStatusReq response (battery, margin) |
| `application/{app_id}/device/{dev_eui}/event/location` | chirpstack → consumers | resolved geolocation if enabled |
| `application/{app_id}/device/{dev_eui}/event/integration` | chirpstack → consumers | generic integration event |
| `application/{app_id}/device/{dev_eui}/command/down` | consumers → chirpstack | enqueue downlink (`{fPort, data, confirmed}`) |

`{app_id}` is a UUID. Look it up via the gRPC API or copy from the ChirpStack UI.

`{dev_eui}` is the 16-hex-char Device EUI, lowercase, no separators.

### 6.3 Operational topic

| Topic | Payload | Meaning |
|---|---|---|
| `gateway/mygw/bridge/state` | `1` or `0` (retained) | VPN/bridge health from local mosquitto's perspective. Exposed in HA as `binary_sensor.mygw_vpn_bridge`. |

---

## 7. ChirpStack API

| Endpoint | Detail |
|---|---|
| URL | `http://10.0.0.10:8080` |
| Protocol | gRPC + HTTP/REST + Web UI multiplexed on the same port |
| Web UI | Browser to the same URL |
| API token | Generate in the UI under **API Keys** (or **Tenant → API Keys**). Do **not** use the JWT signing secret in `/etc/config/chirpstack` — that's not a usable token. |
| gRPC client libs | `chirpstack-api` on pip, also Go/JS/Rust |
| OpenAPI / Swagger | `http://10.0.0.10:8080/api` (UI at `/api/`) |
| Region config | `us915_1` (sub-band 2) only |
| Tenant model | Multi-tenant, but for a single-org install create devices under the default tenant |

### Minimal Python example (gRPC)

```python
import grpc, os
from chirpstack_api import api

server = "10.0.0.10:8080"
api_token = os.environ["CHIRPSTACK_API_TOKEN"]   # generated in the ChirpStack UI; see §11
channel = grpc.insecure_channel(server)
auth_token = [("authorization", f"Bearer {api_token}")]

client = api.DeviceServiceStub(channel)
req = api.ListDevicesRequest()
req.application_id = "<application-uuid>"
req.limit = 100
resp = client.List(req, metadata=auth_token)
for d in resp.result:
    print(d.dev_eui, d.name)
```

### Minimal MQTT subscriber example (Python)

Subscribe to *every device's uplink* and print the codec-decoded object:

```python
import json, os, paho.mqtt.client as mqtt

def on_message(c, u, msg):
    payload = json.loads(msg.payload)
    dev = payload["deviceInfo"]["devEui"]
    obj = payload.get("object", {})  # codec output
    print(f"{dev}: {obj}")

c = mqtt.Client()
c.username_pw_set(os.environ["HA_MQTT_USERNAME"], os.environ["HA_MQTT_PASSWORD"])
c.on_message = on_message
c.connect("10.0.1.10", 1883)
c.subscribe("application/+/device/+/event/up")
c.loop_forever()
```

To **send** a downlink:

```python
payload = {
    "devEui": "0011223344556677",
    "confirmed": False,
    "fPort": 10,
    "data": "SGVsbG8="   # base64-encoded bytes
}
c.publish(f"application/{app_id}/device/{dev_eui}/command/down",
          json.dumps(payload), qos=1)
```

---

## 8. HA / chirp Integration

| Item | Value |
|---|---|
| Custom component | `github.com/modrisb/chirp` (NOT `chirpha` — that's the broken addon) |
| Install path | Via HACS as a custom repository, type Integration |
| Config flow | Settings → Devices & Services → Add Integration → "Chirp" |
| ChirpStack API endpoint | `http://10.0.0.10:8080` |
| ChirpStack API token | Generated in the ChirpStack UI |
| MQTT broker | Reuses HA's MQTT integration (10.0.1.10:1883) |

### HA YAML — bridge health sensor

```yaml
mqtt:
  binary_sensor:
    - name: "Wyolora VPN Bridge"
      unique_id: mygw_vpn_bridge_state
      state_topic: "gateway/mygw/bridge/state"
      payload_on: "1"
      payload_off: "0"
      device_class: connectivity
      icon: mdi:lan-connect
```

---

## 9. Adding a New Device — Flow

1. **Device Profile** (one-time per device type): MAC version, region (US915), optionally attach a JavaScript **codec** that turns raw bytes into named JSON fields. The codec output becomes the `object` key in uplink MQTT events — i.e. the only thing your project / HA actually sees as structured data.
2. **Application** (logical grouping): create or reuse.
3. **Device**: enter DevEUI, optional JoinEUI, AppKey from device label. Pick the device profile.
4. Device powers on, sends OTAA `JoinRequest` over RF.
5. Within seconds the device should appear in chirp's HA entities (initially with no state); after the first uplink, sensor values populate.

### Codec output is the contract

Whatever fields the JavaScript decoder returns end up as keys in `object`. Example codec:

```javascript
function decodeUplink(input) {
  return {
    data: {
      temperature: (input.bytes[0] << 8 | input.bytes[1]) / 100,
      humidity: input.bytes[2],
      battery_mv: (input.bytes[3] << 8 | input.bytes[4])
    },
    warnings: [], errors: []
  };
}
```

Yields an MQTT uplink with:
```json
{
  "deviceInfo": {...},
  "object": {"temperature": 21.5, "humidity": 47, "battery_mv": 3240}
}
```

The codec has an in-UI tester — paste raw bytes, see the decoded output before deploying.

---

## 10. Diagnostic Commands

Run on the Pi (`ssh root@10.0.0.10`):

```sh
# Process check
ps w | grep -E 'chirpstack|mosquitto|concentratord' | grep -v grep

# What's listening
netstat -lntp 2>/dev/null

# Where chirpstack is connected
netstat -ntp 2>/dev/null | grep chirpstack

# Live log stream (concentratord, forwarder, chirpstack, mosquitto)
logread -f

# Sniff local MQTT to see traffic between forwarder and chirpstack
mosquitto_sub -h 127.0.0.1 -t 'us915_1/#' -v

# Sniff application events going across the bridge
mosquitto_sub -h 127.0.0.1 -t 'application/#' -v

# Watch bridge state
mosquitto_sub -h 127.0.0.1 -t 'gateway/mygw/bridge/state' -v

# Check persistence queue file
ls -lh /srv/mosquitto/

# Check concentrator init details (after a restart)
/etc/init.d/chirpstack-concentratord restart
logread -l 50 | grep concentratord
```

From the dev VM (`10.0.1.20` or whatever your VPN-side host is), to sanity-check
the HA broker side:

```sh
mosquitto_sub -h 10.0.1.10 -p 1883 -u chirpstack -P "$HA_MQTT_PASSWORD" -t 'application/#' -v
mosquitto_sub -h 10.0.1.10 -p 1883 -u chirpstack -P "$HA_MQTT_PASSWORD" -t 'gateway/mygw/bridge/state' -v
```

---

## 11. Credentials Reference

**No secret values live in this doc.** Each credential is injected at deploy time from
the environment (a k8s `Secret`, an LXC/`docker` env file, or the gateway's own config),
mirroring `docs/deployment.md` env-var gating and the "secrets never in `design.json`"
rule. The `<placeholders>` in §5 and the code examples mark where the real value goes.

| Credential | Where it's configured | Env var / secret key |
|---|---|---|
| HA mosquitto username (bridge + clients) | `mosquitto.conf` bridge block (§5.4), client examples | `HA_MQTT_USERNAME` (value: `chirpstack`) |
| HA mosquitto password | `mosquitto.conf` bridge block (§5.4), client examples | `HA_MQTT_PASSWORD` |
| ChirpStack API token | Generated in the ChirpStack UI under **API Keys** | `CHIRPSTACK_API_TOKEN` |
| ChirpStack API JWT signing secret (gateway-side; NOT a usable API token) | `chirpstack.toml` `[api] secret` (§5.3) | `CHIRPSTACK_API_SECRET` |
| Pi SSH | `root@10.0.0.10`, key auth (no password in this repo) | n/a — SSH key on the operator host |

### Deploy-time injection

The WireStudio LoRaWAN target reads these from the environment; nothing secret is baked
into the image or this repo.

- **k8s:** store them in a `Secret` and project into the pod:
  ```yaml
  apiVersion: v1
  kind: Secret
  metadata: { name: wirestudio-lorawan }
  type: Opaque
  stringData:
    HA_MQTT_USERNAME: chirpstack
    HA_MQTT_PASSWORD: "<rotate-me>"
    CHIRPSTACK_API_TOKEN: "<token-from-ui>"
  ```
  Reference it from the deployment with `envFrom: [{ secretRef: { name: wirestudio-lorawan } }]`.
- **Proxmox LXC / `docker run` / `podman`:** pass `--env-file lorawan.env` (keep that file
  out of git via `.gitignore`) or individual `-e HA_MQTT_PASSWORD=...` flags.
- **Gateway-side config** (`mosquitto.conf`, `chirpstack.toml`) lives on the Pi, not in this
  repo. The `<ha-mqtt-password>` / `<chirpstack-api-secret>` placeholders in §5 mark where the
  operator substitutes real values during gateway provisioning; regenerate the JWT secret with
  `openssl rand -base64 32`.

> The values previously written here in cleartext should be treated as exposed: rotate the HA
> mosquitto password and regenerate the ChirpStack API secret before relying on them.

---

## 12. Open Items / Known Gaps

- **opkg security patches** (openssl, mbedtls, sqlite, ca-bundle, dnsmasq, openvpn, wireless-regdb) are available but **not applied**. Reboot required. Skipping luci/firewall set due to a libnetfilter dep conflict.
- **No persistent storage limit by bytes** — `max_queued_messages 100000` is a count-based cap. If a multi-day VPN outage with very chatty devices fills overlay, the broker will start dropping new messages silently. Add `max_queued_bytes` if needed.
- **`share_name = "chirpstack"`** uses MQTT shared subscriptions. If a second ChirpStack ever subscribes to the same broker with the same share name, gateway events will round-robin between them. Pick a unique share name per instance.
- **chirpstack upgrade path:** ChirpStack 4.18.0 is upstream but Gateway OS ships 4.17.0. Wait for a Gateway OS release or build a custom image. Don't try to opkg upgrade the chirpstack packages directly — they're not in any opkg feed.
- **HA integration replay during outage:** the bridge replays MQTT events in order, but HA's MQTT timestamps will be "now" rather than original receive time. ChirpStack's metadata (`rxInfo[].time`) preserves the original.

---

## 13. Quick Project-Bootstrap Checklist

When you start building on this from `ubuntu-dev`:

- [ ] Install `python3 chirpstack-api paho-mqtt` (or whatever language SDK)
- [ ] Generate a ChirpStack API token in the UI, store securely
- [ ] Verify access: `nc -vz 10.0.0.10 8080` (gRPC/HTTP) and `nc -vz 10.0.1.10 1883` (MQTT)
- [ ] Subscribe to `application/+/device/+/event/up` on `10.0.1.10:1883` with the chirpstack creds — that's your firehose of decoded sensor data
- [ ] Decide whether your project consumes via MQTT (push), gRPC list/get (pull), or both
- [ ] Add HA bridge-health sensor YAML if not already done
- [ ] Subscribe to `gateway/mygw/bridge/state` in your project too if you want to gate logic on VPN health
