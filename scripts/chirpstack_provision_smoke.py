"""Reversible live ChirpStack provisioning smoke test.

Exercises the full provisioning path (ensure profile + app, create device, set
key, FLUSH DevNonces, read activation) against the live server, then lets you
delete what it made. Uses a clearly-synthetic DevEUI so nothing collides with a
real device and cleanup is a single command. No hardware joins -- this validates
the gRPC writes against the 4.17 server.

    CHIRPSTACK_API_TOKEN=<token> python scripts/chirpstack_provision_smoke.py status
    CHIRPSTACK_API_TOKEN=<token> python scripts/chirpstack_provision_smoke.py provision
    CHIRPSTACK_API_TOKEN=<token> python scripts/chirpstack_provision_smoke.py cleanup

CHIRPSTACK_API_URL defaults to 10.254.0.11:8080. Run `cleanup` when done.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Run as a file (python scripts/foo.py) puts scripts/ on sys.path, not the repo
# root, so bootstrap it -- works regardless of cwd or a stale editable install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wirestudio.targets.lorawan.chirpstack import (  # noqa: E402
    ChirpStackClient,
    ChirpStackUnavailable,
    chirpstack_status,
)

# Synthetic, obviously-not-a-real-device identifiers, easy to spot and delete.
SMOKE_DEV_EUI = "f1f1f1f1f1f10001"
SMOKE_APP = "wirestudio-smoke"
SMOKE_PROFILE = "wirestudio-us915-sub2"
SMOKE_APP_KEY = "00112233445566778899aabbccddeeff"


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cmd = argv[0] if argv else "status"
    client = ChirpStackClient()

    st = chirpstack_status(client)
    print(f"ChirpStack {st['url']}: {'available' if st['available'] else 'UNAVAILABLE'}")
    if not st["available"]:
        print(f"  reason: {st['reason']}")
        return 2

    try:
        if cmd == "status":
            print(f"  tenant: {client.default_tenant_id()}")
            return 0

        if cmd == "provision":
            print(f"  provisioning synthetic device {SMOKE_DEV_EUI} ...")
            result = client.provision_device(
                dev_eui=SMOKE_DEV_EUI,
                app_key=SMOKE_APP_KEY,
                application_name=SMOKE_APP,
                device_profile_name=SMOKE_PROFILE,
                device_name="wirestudio smoke",
            )
            print(f"  application_id   : {result['application_id']}")
            print(f"  device_profile_id: {result['device_profile_id']}")
            print("  FlushDevNonces   : ok")
            act = client.get_activation(SMOKE_DEV_EUI)
            print(f"  activation       : {act or 'not joined (expected, no hardware)'}")
            print(f"\n  cleanup with: python {sys.argv[0]} cleanup")
            return 0

        if cmd == "cleanup":
            client.delete_device(SMOKE_DEV_EUI)
            print(f"  deleted device {SMOKE_DEV_EUI} "
                  f"(left {SMOKE_APP!r} app + {SMOKE_PROFILE!r} profile, both reusable)")
            return 0

        print(f"unknown command {cmd!r}; use status | provision | cleanup")
        return 1
    except ChirpStackUnavailable as exc:
        print(f"  error: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
