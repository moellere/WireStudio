from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from wirestudio.library import default_library
from wirestudio.model import Design
import pytest

from wirestudio.validate import check_board_flash, check_board_revision, dry_run, esphome_available


def _design(board_id: str, mcu: str = "esp32", **board) -> Design:
    return Design(
        schema_version="0.1",
        id="dev1",
        name="Dev 1",
        board={"library_id": board_id, "mcu": mcu, **board},
        power={"supply": "usb", "rail_voltage_v": 3.3},
    )


def test_no_override_is_silent() -> None:
    assert check_board_flash(_design("esp32-s3-devkitc-1"), default_library()) == []


def test_override_below_board_file_is_silent() -> None:
    # The DevKitC-1 floor is 8MB; someone who measured a 4MB part is safe.
    design = _design("esp32-s3-devkitc-1", flash_size_mb=4)
    assert check_board_flash(design, default_library()) == []


def test_override_above_board_file_warns() -> None:
    # N32R16V: correct for that unit, catastrophic on the 8MB SKUs.
    design = _design("esp32-s3-devkitc-1", flash_size_mb=32)
    warnings = check_board_flash(design, default_library())
    assert [w.code for w in warnings] == ["flash_size_override_above_board"]
    assert warnings[0].level == "warn"
    assert "esptool flash-id" in warnings[0].text


def test_override_on_non_esp32_board_warns_it_does_nothing() -> None:
    design = _design("wemos-d1-mini", mcu="esp8266", flash_size_mb=4)
    warnings = check_board_flash(design, default_library())
    assert [w.code for w in warnings] == ["flash_size_override_ignored"]


def test_revision_resolves_the_radio_block() -> None:
    board = default_library().board("heltec-wifi-lora32-v4")
    assert sorted(board.revisions) == ["4.2", "4.3"]
    assert board.radio_for(None).txen == "GPIO46"
    assert board.radio_for("4.2").txen == "GPIO46"
    v43 = board.radio_for("4.3")
    assert v43.txen == "GPIO5"
    assert v43.setup_high == board.radio.setup_high
    with pytest.raises(ValueError, match="no revision '4.9'"):
        board.radio_for("4.9")
    assert board.revision_differences() == {"txen": {"4.2": "GPIO46", "4.3": "GPIO5"}}


def test_board_without_revisions_is_silent() -> None:
    assert check_board_revision(_design("esp32-devkitc-v4"), default_library()) == []


def test_unset_revision_on_a_revised_board_warns_with_the_moved_pins() -> None:
    warnings = check_board_revision(_design("heltec-wifi-lora32-v4"), default_library())
    assert [(w.level, w.code) for w in warnings] == [("warn", "board_revision_unset")]
    assert "radio.txen (4.2: GPIO46, 4.3: GPIO5)" in warnings[0].text
    assert "silkscreen" in warnings[0].text


def test_listed_revision_is_silent() -> None:
    design = _design("heltec-wifi-lora32-v4", revision="4.3")
    assert check_board_revision(design, default_library()) == []


def test_unlisted_revision_is_an_error() -> None:
    design = _design("heltec-wifi-lora32-v4", revision="4.9")
    warnings = check_board_revision(design, default_library())
    assert [(w.level, w.code) for w in warnings] == [("error", "board_revision_unknown")]
    assert "4.2, 4.3" in warnings[0].text
    design = _design("esp32-devkitc-v4", revision="2")
    assert [w.code for w in check_board_revision(design, default_library())] == ["board_revision_unknown"]


def test_unknown_board_defers_to_the_core_validators() -> None:
    design = _design("no-such-board", flash_size_mb=16)
    assert check_board_flash(design, default_library()) == []


def test_esphome_available_true() -> None:
    with patch("shutil.which") as mock_which:
        mock_which.return_value = "/usr/bin/esphome"
        assert esphome_available() is True
        mock_which.assert_called_once_with("esphome")


def test_esphome_available_false() -> None:
    with patch("shutil.which") as mock_which:
        mock_which.return_value = None
        assert esphome_available() is False
        mock_which.assert_called_once_with("esphome")


def test_dry_run_esphome_not_available() -> None:
    with patch("wirestudio.validate.esphome_available", return_value=False):
        success, message = dry_run(Path("test.yaml"))
        assert success is False
        assert "esphome CLI not found" in message


def test_dry_run_success() -> None:
    with patch("wirestudio.validate.esphome_available", return_value=True), patch(
        "subprocess.run"
    ) as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Success "
        mock_result.stderr = "Logs"
        mock_run.return_value = mock_result

        success, message = dry_run(Path("test.yaml"))

        assert success is True
        assert message == "Success Logs"
        mock_run.assert_called_once_with(
            ["esphome", "config", "test.yaml"],
            capture_output=True,
            text=True,
            check=False,
        )


def test_dry_run_failure() -> None:
    with patch("wirestudio.validate.esphome_available", return_value=True), patch(
        "subprocess.run"
    ) as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "Failed "
        mock_result.stderr = "Error logs"
        mock_run.return_value = mock_result

        success, message = dry_run(Path("test.yaml"))

        assert success is False
        assert message == "Failed Error logs"
        mock_run.assert_called_once_with(
            ["esphome", "config", "test.yaml"],
            capture_output=True,
            text=True,
            check=False,
        )


def _harness_raw() -> dict:
    import json
    return json.loads((Path(__file__).resolve().parent.parent / "wirestudio" / "examples" / "actuator-harness.json").read_text())


def test_net_targets_that_resolve_are_silent() -> None:
    from wirestudio.validate import check_net_targets
    assert check_net_targets(Design.model_validate(_harness_raw()), default_library()) == []


def test_net_target_warnings() -> None:
    from wirestudio.validate import check_net_targets
    raw = _harness_raw()
    for c in raw["connections"]:
        if c["component_id"] == "harness" and c["pin_role"] == "P1":
            c["target"] = {"kind": "net", "component_id": "bridge", "net": "nope"}
        if c["component_id"] == "harness" and c["pin_role"] == "P2":
            c["target"] = {"kind": "net", "component_id": "", "net": ""}
        if c["component_id"] == "btn" and c["pin_role"] == "IN":
            c["target"] = {"kind": "net", "component_id": "dial", "net": "A"}
    codes = {(w.code, w.level) for w in check_net_targets(Design.model_validate(raw), default_library())}
    assert ("net_unresolved", "warn") in codes
    assert ("net_unassigned", "info") in codes
    assert ("net_target_on_signal_pin", "warn") in codes
