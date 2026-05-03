from __future__ import annotations

from studio.generate.ascii_gen import render_ascii


def test_garage_motion_matches_golden(garage_motion_design, library, golden_dir):
    expected = (golden_dir / "garage-motion.txt").read_text().rstrip("\n")
    actual = render_ascii(garage_motion_design, library)
    assert actual == expected


def test_box_lines_have_consistent_width(garage_motion_design, library):
    text = render_ascii(garage_motion_design, library)
    lines = text.splitlines()
    widths = {len(line) for line in lines}
    assert len(widths) == 1, f"inconsistent box widths: {widths}"


def test_bom_includes_board_and_components(garage_motion_design, library):
    text = render_ascii(garage_motion_design, library)
    assert "ESP32-DevKitC-V4" in text
    assert "HC-SR501" in text
    assert "BME280" in text
    assert "2x 4.7k resistor" in text


def test_power_budget_summary_present(garage_motion_design, library):
    text = render_ascii(garage_motion_design, library)
    assert "budget 500mA" in text
    assert "OK" in text
