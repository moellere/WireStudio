"""ChirpStack gRPC client for the LoRaWAN target.

Provisions a device against a ChirpStack v4 server: ensure a US915 sub-band 2
device profile and an application exist, create the device, set its key, and
**flush its OTAA DevNonces** on every (re)provision -- the fix for the dominant
"won't join after re-flash/power-cycle" failure (the RPC is
``DeviceService.FlushDevNonces``).

Two load-bearing facts baked in here, both silent-join-failure classes:

* **Region is pinned** to ``Region.US915`` + ``region_config_id="us915_1"`` (the
  gateway's sub-band 2 config). A profile on any other channel mask transmits
  joins the gateway never hears.
* **LoRaWAN 1.0.x stores the AppKey in the ``nwk_key`` field**, not ``app_key``
  (``app_key`` is 1.1-only). We pin MAC version 1.0.4, so the AppKey goes in
  ``nwk_key``.

Heavy deps (grpcio, chirpstack-api) are the ``lorawan`` extra and imported
lazily; without them every call raises ``ChirpStackUnavailable``. Credentials
come from the environment, never ``design.json``:

* ``CHIRPSTACK_API_URL``   gRPC host:port (default ``chirpstack:8080``,
  the typical in-cluster Service name; override for non-k8s deploys)
* ``CHIRPSTACK_API_TOKEN`` Bearer token generated in the ChirpStack UI
* ``CHIRPSTACK_API_TLS``   ``true`` for a TLS channel (default plaintext)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Optional

DEFAULT_URL = "chirpstack:8080"


class ChirpStackUnavailable(RuntimeError):
    """ChirpStack deps are missing or the server could not be reached."""


def _load() -> tuple[object, SimpleNamespace]:
    """Lazy-import grpc + chirpstack-api. Raises ChirpStackUnavailable when
    the lorawan extra isn't installed."""
    try:
        import grpc
        from chirpstack_api import api
        from chirpstack_api.api import (
            application_pb2,
            device_pb2,
            device_profile_pb2,
            tenant_pb2,
        )
        from chirpstack_api.common import common_pb2
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise ChirpStackUnavailable(
            "chirpstack support needs the lorawan extra: "
            "pip install 'wirestudio[lorawan]'"
        ) from exc
    return grpc, SimpleNamespace(
        api=api,
        app=application_pb2,
        dev=device_pb2,
        dp=device_profile_pb2,
        tenant=tenant_pb2,
        common=common_pb2,
    )


@dataclass
class ChirpStackStubs:
    """The four gRPC service stubs. Tests inject fakes; production builds them
    from a channel."""

    device: object
    device_profile: object
    application: object
    tenant: object


class ChirpStackClient:
    def __init__(
        self,
        url: Optional[str] = None,
        token: Optional[str] = None,
        *,
        tls: Optional[bool] = None,
        stubs: Optional[ChirpStackStubs] = None,
    ) -> None:
        self.url = url or os.environ.get("CHIRPSTACK_API_URL") or DEFAULT_URL
        self._token = token if token is not None else os.environ.get("CHIRPSTACK_API_TOKEN", "")
        self._tls = (
            (os.environ.get("CHIRPSTACK_API_TLS", "").lower() == "true")
            if tls is None
            else tls
        )
        self._stubs = stubs

    def is_configured(self) -> bool:
        return bool(self.url and self._token)

    @property
    def _auth(self) -> list[tuple[str, str]]:
        return [("authorization", f"Bearer {self._token}")]

    def _get_stubs(self) -> ChirpStackStubs:
        if self._stubs is None:
            grpc, m = _load()
            channel = (
                grpc.secure_channel(self.url, grpc.ssl_channel_credentials())
                if self._tls
                else grpc.insecure_channel(self.url)
            )
            self._stubs = ChirpStackStubs(
                device=m.api.DeviceServiceStub(channel),
                device_profile=m.api.DeviceProfileServiceStub(channel),
                application=m.api.ApplicationServiceStub(channel),
                tenant=m.api.TenantServiceStub(channel),
            )
        return self._stubs

    # -- read-only -------------------------------------------------------

    def ping(self) -> None:
        """Read-only reachability + auth check (lists one tenant). Raises
        ChirpStackUnavailable on any transport/auth error."""
        grpc, m = _load()
        try:
            self._get_stubs().tenant.List(
                m.tenant.ListTenantsRequest(limit=1), metadata=self._auth
            )
        except grpc.RpcError as exc:
            raise ChirpStackUnavailable(f"ChirpStack unreachable: {_rpc_msg(exc)}") from exc

    def default_tenant_id(self) -> str:
        grpc, m = _load()
        try:
            resp = self._get_stubs().tenant.List(
                m.tenant.ListTenantsRequest(limit=1), metadata=self._auth
            )
        except grpc.RpcError as exc:
            raise ChirpStackUnavailable(_rpc_msg(exc)) from exc
        if not resp.result:
            raise ChirpStackUnavailable("ChirpStack has no tenant to provision under")
        return resp.result[0].id

    def get_activation(self, dev_eui: str) -> Optional[dict]:
        """Return the device's activation (dev_addr, frame counters) or None
        if it hasn't joined yet."""
        grpc, m = _load()
        try:
            resp = self._get_stubs().device.GetActivation(
                m.dev.GetDeviceActivationRequest(dev_eui=dev_eui), metadata=self._auth
            )
        except grpc.RpcError as exc:
            if exc.code() == grpc.StatusCode.NOT_FOUND:
                return None
            raise ChirpStackUnavailable(_rpc_msg(exc)) from exc
        act = resp.device_activation
        if not act.dev_addr:
            return None
        return {"dev_addr": act.dev_addr, "f_cnt_up": act.f_cnt_up}

    # -- mutations -------------------------------------------------------

    def ensure_application(self, name: str, *, tenant_id: str) -> str:
        grpc, m = _load()
        stubs = self._get_stubs()
        try:
            resp = stubs.application.List(
                m.app.ListApplicationsRequest(limit=100, tenant_id=tenant_id, search=name),
                metadata=self._auth,
            )
            for item in resp.result:
                if item.name == name:
                    return item.id
            created = stubs.application.Create(
                m.app.CreateApplicationRequest(
                    application=m.app.Application(name=name, tenant_id=tenant_id)
                ),
                metadata=self._auth,
            )
        except grpc.RpcError as exc:
            raise ChirpStackUnavailable(_rpc_msg(exc)) from exc
        return created.id

    def ensure_device_profile(
        self, name: str, *, tenant_id: str, codec: Optional[str] = None
    ) -> str:
        """Ensure a US915 sub-band 2 OTAA profile exists; return its id. When
        `codec` is given, set it as the profile's JS decodeUplink (refreshing an
        existing profile too) so the device's uplinks decode into named fields.

        Pins region US915 + region_config_id ``us915_1`` (the gateway's
        sub-band 2 config) and MAC version 1.0.4 / RP002-1.0.0.
        """
        grpc, m = _load()
        stubs = self._get_stubs()
        try:
            resp = stubs.device_profile.List(
                m.dp.ListDeviceProfilesRequest(limit=100, tenant_id=tenant_id, search=name),
                metadata=self._auth,
            )
            for item in resp.result:
                if item.name == name and item.region == m.common.Region.US915:
                    if codec is not None:
                        existing = stubs.device_profile.Get(
                            m.dp.GetDeviceProfileRequest(id=item.id), metadata=self._auth
                        ).device_profile
                        existing.payload_codec_runtime = m.dp.CodecRuntime.JS
                        existing.payload_codec_script = codec
                        stubs.device_profile.Update(
                            m.dp.UpdateDeviceProfileRequest(device_profile=existing),
                            metadata=self._auth,
                        )
                    return item.id
            profile = m.dp.DeviceProfile(
                name=name,
                tenant_id=tenant_id,
                region=m.common.Region.US915,
                region_config_id="us915_1",
                mac_version=m.common.MacVersion.LORAWAN_1_0_4,
                reg_params_revision=m.common.RegParamsRevision.RP002_1_0_0,
                adr_algorithm_id="default",
                supports_otaa=True,
                uplink_interval=3600,
            )
            if codec is not None:
                profile.payload_codec_runtime = m.dp.CodecRuntime.JS
                profile.payload_codec_script = codec
            created = stubs.device_profile.Create(
                m.dp.CreateDeviceProfileRequest(device_profile=profile), metadata=self._auth
            )
        except grpc.RpcError as exc:
            raise ChirpStackUnavailable(_rpc_msg(exc)) from exc
        return created.id

    def create_device(
        self,
        dev_eui: str,
        name: str,
        application_id: str,
        device_profile_id: str,
        *,
        join_eui: Optional[str] = None,
    ) -> None:
        """Create the device. Idempotent: an existing DevEUI is left in place."""
        grpc, m = _load()
        device = m.dev.Device(
            dev_eui=dev_eui,
            name=name,
            application_id=application_id,
            device_profile_id=device_profile_id,
        )
        if join_eui:
            device.join_eui = join_eui
        try:
            self._get_stubs().device.Create(
                m.dev.CreateDeviceRequest(device=device), metadata=self._auth
            )
        except grpc.RpcError as exc:
            if exc.code() != grpc.StatusCode.ALREADY_EXISTS:
                raise ChirpStackUnavailable(_rpc_msg(exc)) from exc

    def set_device_keys(self, dev_eui: str, app_key: str) -> None:
        """Set the device's root key. For our pinned LoRaWAN 1.0.4 devices the
        AppKey lives in the ``nwk_key`` field (``app_key`` is 1.1-only).
        Idempotent: updates the key if one already exists."""
        grpc, m = _load()
        stubs = self._get_stubs()
        keys = m.dev.DeviceKeys(dev_eui=dev_eui, nwk_key=app_key)
        try:
            stubs.device.CreateKeys(
                m.dev.CreateDeviceKeysRequest(device_keys=keys), metadata=self._auth
            )
        except grpc.RpcError as exc:
            if exc.code() == grpc.StatusCode.ALREADY_EXISTS:
                try:
                    stubs.device.UpdateKeys(
                        m.dev.UpdateDeviceKeysRequest(device_keys=keys), metadata=self._auth
                    )
                except grpc.RpcError as upd_exc:
                    raise ChirpStackUnavailable(_rpc_msg(upd_exc)) from upd_exc
            else:
                raise ChirpStackUnavailable(_rpc_msg(exc)) from exc

    def delete_device(self, dev_eui: str) -> None:
        """Delete a device. Idempotent: a missing DevEUI is a no-op. Used to
        clean up after a provisioning smoke test."""
        grpc, m = _load()
        try:
            self._get_stubs().device.Delete(
                m.dev.DeleteDeviceRequest(dev_eui=dev_eui), metadata=self._auth
            )
        except grpc.RpcError as exc:
            if exc.code() != grpc.StatusCode.NOT_FOUND:
                raise ChirpStackUnavailable(_rpc_msg(exc)) from exc

    def set_device_codec(self, dev_eui: str, codec: str) -> str:
        """Set the JS decodeUplink codec on the device's profile so ChirpStack
        decodes its uplinks into named ``object`` fields. Works on a device
        whatever profile it's on. Returns the device_profile_id."""
        grpc, m = _load()
        stubs = self._get_stubs()
        try:
            dev = stubs.device.Get(
                m.dev.GetDeviceRequest(dev_eui=dev_eui), metadata=self._auth
            )
            profile_id = dev.device.device_profile_id
            resp = stubs.device_profile.Get(
                m.dp.GetDeviceProfileRequest(id=profile_id), metadata=self._auth
            )
            profile = resp.device_profile
            profile.payload_codec_runtime = m.dp.CodecRuntime.JS
            profile.payload_codec_script = codec
            stubs.device_profile.Update(
                m.dp.UpdateDeviceProfileRequest(device_profile=profile), metadata=self._auth
            )
        except grpc.RpcError as exc:
            raise ChirpStackUnavailable(_rpc_msg(exc)) from exc
        return profile_id

    def get_device_codec(self, dev_eui: str) -> dict:
        """Read-only: what codec is on the device's profile? For diagnosing
        whether ``object`` decoding will happen."""
        grpc, m = _load()
        stubs = self._get_stubs()
        try:
            dev = stubs.device.Get(
                m.dev.GetDeviceRequest(dev_eui=dev_eui), metadata=self._auth
            )
            profile_id = dev.device.device_profile_id
            profile = stubs.device_profile.Get(
                m.dp.GetDeviceProfileRequest(id=profile_id), metadata=self._auth
            ).device_profile
        except grpc.RpcError as exc:
            raise ChirpStackUnavailable(_rpc_msg(exc)) from exc
        script = profile.payload_codec_script or ""
        return {
            "device_profile_id": profile_id,
            "device_profile_name": profile.name,
            "codec_runtime": m.dp.CodecRuntime.Name(profile.payload_codec_runtime),
            "has_codec": bool(script),
            "codec_chars": len(script),
        }

    def flush_dev_nonces(self, dev_eui: str) -> None:
        """Flush the device's used OTAA DevNonces (the UI's "Flush OTAA device
        nonces"). Call on every (re)provision so a freshly-flashed device,
        whose nonce counter reset, joins cleanly instead of being dropped as a
        replay."""
        grpc, m = _load()
        try:
            self._get_stubs().device.FlushDevNonces(
                m.dev.FlushDevNoncesRequest(dev_eui=dev_eui), metadata=self._auth
            )
        except grpc.RpcError as exc:
            raise ChirpStackUnavailable(_rpc_msg(exc)) from exc

    def provision_device(
        self,
        *,
        dev_eui: str,
        app_key: str,
        application_name: str,
        device_profile_name: str,
        device_name: Optional[str] = None,
        join_eui: Optional[str] = None,
        codec: Optional[str] = None,
    ) -> dict:
        """Full (re)provision: ensure profile (with codec) + app, create device,
        set key, flush nonces. Returns the resolved ids. Side-effecting against
        the live server."""
        tenant_id = self.default_tenant_id()
        application_id = self.ensure_application(application_name, tenant_id=tenant_id)
        device_profile_id = self.ensure_device_profile(
            device_profile_name, tenant_id=tenant_id, codec=codec
        )
        self.create_device(
            dev_eui,
            device_name or dev_eui,
            application_id,
            device_profile_id,
            join_eui=join_eui,
        )
        self.set_device_keys(dev_eui, app_key)
        self.flush_dev_nonces(dev_eui)
        return {
            "dev_eui": dev_eui,
            "application_id": application_id,
            "device_profile_id": device_profile_id,
        }


def _rpc_msg(exc) -> str:
    try:
        return f"{exc.code().name}: {exc.details()}"
    except Exception:  # pragma: no cover - defensive
        return str(exc)


def chirpstack_status(client: Optional[ChirpStackClient] = None) -> dict:
    """Probe ChirpStack. Shape mirrors the other feature-gate status endpoints
    (jlcpcb/enclosure/fleet): `available` is the headline the UI keys off.
    Read-only -- safe to call against the live server."""
    client = client or ChirpStackClient()
    if not client.is_configured():
        reason = (
            "CHIRPSTACK_API_TOKEN not set" if client.url else "CHIRPSTACK_API_URL not set"
        )
        return {"available": False, "url": client.url or None, "reason": reason}
    try:
        client.ping()
        return {"available": True, "url": client.url, "reason": None}
    except ChirpStackUnavailable as exc:
        return {"available": False, "url": client.url, "reason": str(exc)}
