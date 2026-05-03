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


def test_awning_matches_golden(awning_control_design, library, golden_dir):
    expected = (golden_dir / "awning-control.txt").read_text().rstrip("\n")
    actual = render_ascii(awning_control_design, library)
    assert actual == expected


def test_awning_box_consistent_width(awning_control_design, library):
    text = render_ascii(awning_control_design, library)
    widths = {len(line) for line in text.splitlines()}
    assert len(widths) == 1


def test_awning_warning_surfaced(awning_control_design, library):
    text = render_ascii(awning_control_design, library)
    # awning still has a deferred-extras warning, but the *kind* of deferral
    # changed once the expander_pin refactor landed.
    assert "[info] pwm_and_cover_in_extras" in text


def test_wasserpir_matches_golden(wasserpir_design, library, golden_dir):
    expected = (golden_dir / "wasserpir.txt").read_text().rstrip("\n")
    assert render_ascii(wasserpir_design, library) == expected


def test_oled_matches_golden(oled_design, library, golden_dir):
    expected = (golden_dir / "oled.txt").read_text().rstrip("\n")
    assert render_ascii(oled_design, library) == expected


def test_bluemotion_matches_golden(bluemotion_design, library, golden_dir):
    expected = (golden_dir / "bluemotion.txt").read_text().rstrip("\n")
    assert render_ascii(bluemotion_design, library) == expected


def test_bluemotion_box_consistent_width(bluemotion_design, library):
    widths = {len(line) for line in render_ascii(bluemotion_design, library).splitlines()}
    assert len(widths) == 1


def test_distance_sensor_matches_golden(distance_sensor_design, library, golden_dir):
    expected = (golden_dir / "distance-sensor.txt").read_text().rstrip("\n")
    assert render_ascii(distance_sensor_design, library) == expected


def test_securitypanel_matches_golden(securitypanel_design, library, golden_dir):
    expected = (golden_dir / "securitypanel.txt").read_text().rstrip("\n")
    assert render_ascii(securitypanel_design, library) == expected


def test_securitypanel_renders_expander_pin_lines(securitypanel_design, library):
    text = render_ascii(securitypanel_design, library)
    assert "IN    -> mcp_hub.4 INPUT inverted" in text
    assert "OUT   -> mcp_hub.3 OUTPUT inverted" in text


def test_awning_no_longer_shows_expander_pins_in_extras_warning(awning_control_design, library):
    text = render_ascii(awning_control_design, library)
    assert "expander_pins_in_extras" not in text
