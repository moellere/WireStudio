from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Feature-gated: skip the whole module on an ESPHome-only install.
grpc = pytest.importorskip("grpc")
pytest.importorskip("chirpstack_api")

from wirestudio.targets.lorawan import chirpstack as cs  # noqa: E402


class _RpcError(grpc.RpcError):
    def __init__(self, code: "grpc.StatusCode") -> None:
        self._code = code

    def code(self):
        return self._code

    def details(self):
        return "simulated"


def _stubs() -> cs.ChirpStackStubs:
    return cs.ChirpStackStubs(
        device=MagicMock(),
        device_profile=MagicMock(),
        application=MagicMock(),
        tenant=MagicMock(),
    )


def _client(stubs: cs.ChirpStackStubs) -> cs.ChirpStackClient:
    return cs.ChirpStackClient(url="host:8080", token="tok", stubs=stubs)


# -- configuration / status ------------------------------------------------


def test_is_configured_requires_token():
    assert not cs.ChirpStackClient(url="host:8080", token="").is_configured()
    assert cs.ChirpStackClient(url="host:8080", token="t").is_configured()


def test_status_unconfigured_reports_missing_token():
    out = cs.chirpstack_status(cs.ChirpStackClient(url="host:8080", token=""))
    assert out["available"] is False
    assert "TOKEN" in out["reason"].upper()


def test_status_available_when_ping_succeeds():
    stubs = _stubs()
    stubs.tenant.List.return_value = SimpleNamespace(result=[SimpleNamespace(id="t1")])
    out = cs.chirpstack_status(_client(stubs))
    assert out == {"available": True, "url": "host:8080", "reason": None}


def test_status_unavailable_on_rpc_error():
    stubs = _stubs()
    stubs.tenant.List.side_effect = _RpcError(grpc.StatusCode.UNAVAILABLE)
    out = cs.chirpstack_status(_client(stubs))
    assert out["available"] is False
    assert "UNAVAILABLE" in out["reason"]


def test_status_degrades_when_deps_missing(monkeypatch):
    def _boom():
        raise cs.ChirpStackUnavailable("pip install 'wirestudio[lorawan]'")

    monkeypatch.setattr(cs, "_load", _boom)
    out = cs.chirpstack_status(cs.ChirpStackClient(url="host:8080", token="t"))
    assert out["available"] is False
    assert "lorawan" in out["reason"]


# -- ensure_* idempotency --------------------------------------------------


def test_ensure_application_returns_existing():
    stubs = _stubs()
    stubs.application.List.return_value = SimpleNamespace(
        result=[SimpleNamespace(id="app-1", name="myapp")]
    )
    assert _client(stubs).ensure_application("myapp", tenant_id="t") == "app-1"
    stubs.application.Create.assert_not_called()


def test_ensure_application_creates_when_absent():
    stubs = _stubs()
    stubs.application.List.return_value = SimpleNamespace(result=[])
    stubs.application.Create.return_value = SimpleNamespace(id="app-new")
    assert _client(stubs).ensure_application("myapp", tenant_id="t") == "app-new"
    stubs.application.Create.assert_called_once()


def test_ensure_device_profile_matches_name_and_region():
    stubs = _stubs()
    from chirpstack_api.common import common_pb2

    stubs.device_profile.List.return_value = SimpleNamespace(
        result=[SimpleNamespace(id="dp-1", name="us915", region=common_pb2.Region.US915)]
    )
    assert _client(stubs).ensure_device_profile("us915", tenant_id="t") == "dp-1"
    stubs.device_profile.Create.assert_not_called()


def test_ensure_device_profile_pins_us915_subband2():
    stubs = _stubs()
    stubs.device_profile.List.return_value = SimpleNamespace(result=[])
    stubs.device_profile.Create.return_value = SimpleNamespace(id="dp-new")
    from chirpstack_api.common import common_pb2

    assert _client(stubs).ensure_device_profile("us915", tenant_id="t") == "dp-new"
    profile = stubs.device_profile.Create.call_args.args[0].device_profile
    assert profile.region == common_pb2.Region.US915
    assert profile.region_config_id == "us915_1"
    assert profile.mac_version == common_pb2.MacVersion.LORAWAN_1_0_4
    assert profile.supports_otaa is True


# -- device / keys / nonces ------------------------------------------------


def test_create_device_swallows_already_exists():
    stubs = _stubs()
    stubs.device.Create.side_effect = _RpcError(grpc.StatusCode.ALREADY_EXISTS)
    # Must not raise.
    _client(stubs).create_device("0011223344556677", "dev", "app", "dp")


def test_create_device_wraps_other_errors_as_chirpstack_unavailable():
    # Transport / auth / permission errors get converted to ChirpStackUnavailable
    # so the FastAPI handlers (which only catch ChirpStackUnavailable) turn them
    # into a 502 with the gRPC status + details, not a bare unhandled 500.
    stubs = _stubs()
    stubs.device.Create.side_effect = _RpcError(grpc.StatusCode.PERMISSION_DENIED)
    with pytest.raises(cs.ChirpStackUnavailable, match="PERMISSION_DENIED"):
        _client(stubs).create_device("0011223344556677", "dev", "app", "dp")


def test_set_device_keys_writes_appkey_into_nwk_key():
    # The LoRaWAN 1.0.x footgun: AppKey belongs in nwk_key, not app_key.
    stubs = _stubs()
    _client(stubs).set_device_keys("0011223344556677", "ab" * 16)
    keys = stubs.device.CreateKeys.call_args.args[0].device_keys
    assert keys.nwk_key == "ab" * 16
    assert keys.app_key == ""


def test_set_device_keys_updates_when_exists():
    stubs = _stubs()
    stubs.device.CreateKeys.side_effect = _RpcError(grpc.StatusCode.ALREADY_EXISTS)
    _client(stubs).set_device_keys("0011223344556677", "cd" * 16)
    stubs.device.UpdateKeys.assert_called_once()


def test_flush_dev_nonces_calls_rpc_with_dev_eui():
    stubs = _stubs()
    _client(stubs).flush_dev_nonces("0011223344556677")
    req = stubs.device.FlushDevNonces.call_args.args[0]
    assert req.dev_eui == "0011223344556677"


def test_default_tenant_id_wraps_rpc_error_as_chirpstack_unavailable():
    # The first call of every provisioning chain. A bad token surfaces here
    # (UNAUTHENTICATED), and the wrap is what turns the otherwise-unhandled
    # 500 the user saw into a 502 with "UNAUTHENTICATED:" in the body.
    stubs = _stubs()
    stubs.tenant.List.side_effect = _RpcError(grpc.StatusCode.UNAUTHENTICATED)
    with pytest.raises(cs.ChirpStackUnavailable, match="UNAUTHENTICATED"):
        _client(stubs).default_tenant_id()


def test_flush_dev_nonces_wraps_rpc_error_as_chirpstack_unavailable():
    stubs = _stubs()
    stubs.device.FlushDevNonces.side_effect = _RpcError(grpc.StatusCode.UNAVAILABLE)
    with pytest.raises(cs.ChirpStackUnavailable, match="UNAVAILABLE"):
        _client(stubs).flush_dev_nonces("0011223344556677")


def test_delete_device_calls_rpc():
    stubs = _stubs()
    _client(stubs).delete_device("0011223344556677")
    assert stubs.device.Delete.call_args.args[0].dev_eui == "0011223344556677"


def test_delete_device_swallows_not_found():
    stubs = _stubs()
    stubs.device.Delete.side_effect = _RpcError(grpc.StatusCode.NOT_FOUND)
    _client(stubs).delete_device("0011223344556677")  # must not raise


def test_get_activation_returns_none_when_not_joined():
    stubs = _stubs()
    stubs.device.GetActivation.side_effect = _RpcError(grpc.StatusCode.NOT_FOUND)
    assert _client(stubs).get_activation("0011223344556677") is None


def test_get_activation_returns_dev_addr():
    stubs = _stubs()
    stubs.device.GetActivation.return_value = SimpleNamespace(
        device_activation=SimpleNamespace(dev_addr="01020304", f_cnt_up=7)
    )
    assert _client(stubs).get_activation("0011223344556677") == {
        "dev_addr": "01020304",
        "f_cnt_up": 7,
    }


# -- provisioning orchestration --------------------------------------------


def test_provision_device_flushes_nonces():
    stubs = _stubs()
    stubs.tenant.List.return_value = SimpleNamespace(result=[SimpleNamespace(id="t1")])
    stubs.application.List.return_value = SimpleNamespace(result=[])
    stubs.application.Create.return_value = SimpleNamespace(id="app1")
    stubs.device_profile.List.return_value = SimpleNamespace(result=[])
    stubs.device_profile.Create.return_value = SimpleNamespace(id="dp1")

    out = _client(stubs).provision_device(
        dev_eui="0011223344556677",
        app_key="ef" * 16,
        application_name="wirestudio",
        device_profile_name="us915-sub2",
    )
    assert out == {
        "dev_eui": "0011223344556677",
        "application_id": "app1",
        "device_profile_id": "dp1",
    }
    # The §2.1 fix must run on every provision.
    stubs.device.FlushDevNonces.assert_called_once()
    stubs.device.Create.assert_called_once()
    stubs.device.CreateKeys.assert_called_once()
