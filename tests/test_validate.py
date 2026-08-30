from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from wirestudio.library import default_library
from wirestudio.model import Design
from wirestudio.validate import check_board_flash, dry_run, esphome_available


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
