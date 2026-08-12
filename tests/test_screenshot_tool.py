"""Network-free tests for the reproducible README screenshot configuration."""

import importlib.util
from pathlib import Path

import pytest


TOOL_PATH = Path(__file__).parents[1] / "tools" / "screenshot" / "make_screenshot.py"
SPEC = importlib.util.spec_from_file_location("make_screenshot", TOOL_PATH)
make_screenshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(make_screenshot)


def test_parse_app_version_reads_source_assignment():
    source = '# comment\nAPP_VERSION = "2.3.4"\n'

    assert make_screenshot.parse_app_version(source) == "2.3.4"


def test_parse_app_version_rejects_missing_assignment():
    with pytest.raises(ValueError, match="could not find APP_VERSION"):
        make_screenshot.parse_app_version("VERSION = '2.3.4'\n")


def test_capture_config_seeds_real_ui_seams_and_dark_first_order():
    config = make_screenshot.build_capture_config(48123, "1.4.0")

    assert config["url"] == "http://127.0.0.1:48123/index.html"
    assert (config["width"], config["height"], config["scale"]) == (1800, 1120, 0.5)
    assert config["shots"] == [
        {"name": "dark", "script": "applyTheme('dark')"},
        {"name": "light", "script": "applyTheme('light')"},
    ]
    for seam in ("META=", "rows=", "buildSeg", "buildChips", "buildHead", "setConn", "render"):
        assert seam in config["setup"]
    assert "v'+META.version" in config["setup"]
    assert "1.4.0" in config["setup"]
    assert "Client Devices" in config["setup"]
    assert "WiFi Client Connected" in config["setup"]


def test_scene_matches_controller_metadata_and_uses_populated_millisecond_rows():
    meta = make_screenshot.scene.META
    rows = make_screenshot.scene.ROWS

    assert meta["time_ranges"] == ["1 Hour", "1 Day", "1 Week", "1 Month"]
    assert meta["default_time_range"] == "1 Day"
    assert meta["log_types"] == ["General", "Audit"]
    assert meta["default_log_type"] == "General"
    assert meta["categories"][0] == "Client Devices"
    assert meta["events"] == [
        "WiFi Client Connected",
        "WiFi Client Disconnected",
        "WiFi Client Roamed",
        "Wired Client Connected",
        "Wired Client Disconnected",
    ]
    assert len(rows) == 13
    assert all(row["datetime_raw"] > 1_000_000_000_000 for row in rows)
    assert all(
        {"datetime", "site", "category", "event", "severity", "description", "client", "mac"}
        <= row.keys()
        for row in rows
    )
