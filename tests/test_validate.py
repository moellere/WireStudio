from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from wirestudio.validate import dry_run, esphome_available


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
