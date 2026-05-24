"""Read-only ChirpStack smoke check.

    CHIRPSTACK_API_TOKEN=<token> python -m wirestudio.targets.lorawan status

Probes the server (auth + reachability) and lists tenants, applications, and
US915 device profiles. Performs no writes -- safe against the live server.
Provisioning (create device/keys, flush nonces) is intentionally not exposed
here; it runs through the client API under explicit control.
"""
from __future__ import annotations

import argparse
import sys

from wirestudio.targets.lorawan.chirpstack import (
    ChirpStackClient,
    ChirpStackUnavailable,
    chirpstack_status,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wirestudio.targets.lorawan")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="probe ChirpStack and list tenants/apps/profiles (read-only)")
    args = parser.parse_args(argv)

    if args.cmd == "status":
        status = chirpstack_status()
        print(f"ChirpStack {status['url']}: "
              f"{'available' if status['available'] else 'UNAVAILABLE'}")
        if not status["available"]:
            print(f"  reason: {status['reason']}")
            return 2

        client = ChirpStackClient()
        from chirpstack_api.api import application_pb2, device_profile_pb2
        try:
            tenant_id = client.default_tenant_id()
            print(f"  tenant: {tenant_id}")
            stubs = client._get_stubs()
            apps = stubs.application.List(
                application_pb2.ListApplicationsRequest(limit=100, tenant_id=tenant_id),
                metadata=client._auth,
            )
            print(f"  applications ({apps.total_count}):")
            for a in apps.result:
                print(f"    {a.id}  {a.name}")
            profiles = stubs.device_profile.List(
                device_profile_pb2.ListDeviceProfilesRequest(limit=100, tenant_id=tenant_id),
                metadata=client._auth,
            )
            print(f"  device profiles ({profiles.total_count}):")
            for p in profiles.result:
                print(f"    {p.id}  {p.name}  region={p.region}")
        except ChirpStackUnavailable as exc:
            print(f"  error: {exc}")
            return 2
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
