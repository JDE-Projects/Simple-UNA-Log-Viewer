"""
Tests for the non-UI parsing/formatting logic in simple_una_log_viewer.py:
CSV cell safety, version comparison, message templating, event-row
building/filtering, and export sort order. No controller, no network, no
Qt window.
"""

from datetime import datetime

import simple_una_log_viewer as app


# ─────────────────────────────────────────────────────────────
#  _csv_safe
# ─────────────────────────────────────────────────────────────
def test_csv_safe_quotes_formula_prefixes():
    for prefix in ("=", "+", "-", "@", "\t", "\r"):
        value = prefix + "cmd|' /C calc'!A1"
        assert app._csv_safe(value) == "'" + value


def test_csv_safe_leaves_ordinary_text_unchanged():
    assert app._csv_safe("Living Room AP") == "Living Room AP"


def test_csv_safe_empty_string_stays_empty():
    assert app._csv_safe("") == ""


def test_csv_safe_none_becomes_empty_string():
    assert app._csv_safe(None) == ""


def test_csv_safe_minus_five_is_quoted_on_purpose():
    # A bare "-5" starts with "-", so it is treated the same as a formula lead-in.
    assert app._csv_safe("-5") == "'-5"


def test_csv_safe_hyphen_in_the_middle_is_not_quoted():
    assert app._csv_safe("a-b") == "a-b"


# ─────────────────────────────────────────────────────────────
#  _parse_version
# ─────────────────────────────────────────────────────────────
def test_parse_version_full_semver_with_v_prefix():
    assert app._parse_version("v1.2.3") == (1, 2, 3)


def test_parse_version_two_part():
    assert app._parse_version("1.2") == (1, 2, 0)


def test_parse_version_one_part():
    assert app._parse_version("1") == (1, 0, 0)


def test_parse_version_empty_string():
    assert app._parse_version("") == (0, 0, 0)


def test_parse_version_junk_is_sane():
    assert app._parse_version("not-a-version") == (0, 0, 0)


def test_parse_version_comparisons_used_by_update_check():
    assert app._parse_version("1.3.1") > app._parse_version("1.3.0")
    assert app._parse_version("1.10.0") > app._parse_version("1.9.0")


# ─────────────────────────────────────────────────────────────
#  Api._render_message
# ─────────────────────────────────────────────────────────────
def test_render_message_substitutes_known_token():
    api = app.Api()
    out = api._render_message("Hello {TOKEN}", {"TOKEN": {"name": "Bob"}})
    assert out == "Hello Bob"


def test_render_message_leaves_unknown_token_untouched():
    api = app.Api()
    out = api._render_message("Hi {UNKNOWN}", {"TOKEN": {"name": "Bob"}})
    assert out == "Hi {UNKNOWN}"


def test_render_message_tolerates_none_params():
    api = app.Api()
    assert api._render_message("Hello {TOKEN}", None) == "Hello {TOKEN}"


def test_render_message_tolerates_non_dict_params():
    api = app.Api()
    assert api._render_message("Hello {TOKEN}", ["not", "a", "dict"]) == "Hello {TOKEN}"


def test_render_message_empty_template():
    api = app.Api()
    assert api._render_message("", {"TOKEN": {"name": "Bob"}}) == ""


# ─────────────────────────────────────────────────────────────
#  Api._build_event_row
# ─────────────────────────────────────────────────────────────
def test_build_event_row_realistic_item():
    api = app.Api()
    item = {
        "timestamp": 1700000000000,
        "key": "CLIENT_CONNECTED_WIRELESS_2",
        "category": "CLIENT_DEVICES",
        "severity": "INFO",
        "title_raw": "WiFi Client Connected",
        "message_raw": "{CLIENT} connected to {WLAN}",
        "parameters": {
            "CLIENT": {"hostname": "Johns-Laptop", "id": "aa:bb:cc:dd:ee:ff", "name": "fallback-name"},
            "DEVICE": {"name": "Living Room AP"},
            "WLAN": {"name": "Home-WiFi"},
            "NETWORK": {"name": "Default"},
        },
    }
    row = api._build_event_row(item, "My Site", "mysite")

    assert row["datetime"] == datetime.fromtimestamp(
        1700000000000 / 1000).strftime("%Y-%m-%d %H:%M:%S")
    assert row["datetime_raw"] == 1700000000000
    assert row["site"] == "My Site"
    assert row["site_id"] == "mysite"
    assert row["category"] == app.CATEGORY_ENUM_TO_LABEL["CLIENT_DEVICES"] == "Client Devices"
    assert row["category_enum"] == "CLIENT_DEVICES"
    assert row["event"] == "WiFi Client Connected"
    assert row["event_key"] == "CLIENT_CONNECTED_WIRELESS_2"
    assert row["severity"] == "INFO"
    assert row["client"] == "Johns-Laptop"
    assert row["mac"] == "aa:bb:cc:dd:ee:ff"
    assert row["ap"] == "Living Room AP"
    assert row["ssid"] == "Home-WiFi"
    assert row["network"] == "Default"


def test_build_event_row_missing_timestamp_does_not_raise():
    api = app.Api()
    row = api._build_event_row({}, "Site", "site")
    assert isinstance(row["datetime"], str)
    assert row["client"] == ""
    assert row["mac"] == ""
    assert row["ap"] == ""
    assert row["ssid"] == ""
    assert row["network"] == ""


def test_build_event_row_non_numeric_timestamp_does_not_raise():
    api = app.Api()
    item = {"timestamp": "not-a-number"}
    row = api._build_event_row(item, "Site", "site")
    assert row["datetime_raw"] == 0
    assert isinstance(row["datetime"], str)


def test_build_event_row_parameters_as_list_does_not_raise():
    api = app.Api()
    item = {"timestamp": 1700000000000, "parameters": ["not", "a", "dict"]}
    row = api._build_event_row(item, "Site", "site")
    assert row["client"] == ""
    assert row["mac"] == ""
    assert row["ap"] == ""
    assert row["ssid"] == ""
    assert row["network"] == ""
    assert row["category"] == "Other"
    assert row["event"] == ""


# ─────────────────────────────────────────────────────────────
#  Api._filter_rows
# ─────────────────────────────────────────────────────────────
def _sample_rows():
    return [
        {"event_key": "CLIENT_CONNECTED_WIRELESS_2", "category_enum": "CLIENT_DEVICES"},
        {"event_key": "CLIENT_DISCONNECTED_WIRELESS_2", "category_enum": "CLIENT_DEVICES"},
        {"event_key": "VPN_CONNECTED", "category_enum": "VPN"},
    ]


def test_filter_rows_no_filters_returns_everything():
    api = app.Api()
    rows = _sample_rows()
    assert api._filter_rows(rows, [], []) == rows


def test_filter_rows_by_event_key_only():
    api = app.Api()
    rows = _sample_rows()
    out = api._filter_rows(rows, ["CLIENT_CONNECTED_WIRELESS_2"], [])
    assert out == [rows[0]]


def test_filter_rows_by_category_only():
    api = app.Api()
    rows = _sample_rows()
    out = api._filter_rows(rows, [], ["VPN"])
    assert out == [rows[2]]


def test_filter_rows_by_both_event_and_category():
    api = app.Api()
    rows = _sample_rows()
    out = api._filter_rows(rows, ["CLIENT_CONNECTED_WIRELESS_2"], ["CLIENT_DEVICES"])
    assert out == [rows[0]]
    # A row matching only one of the two filters is excluded.
    out2 = api._filter_rows(rows, ["CLIENT_CONNECTED_WIRELESS_2"], ["VPN"])
    assert out2 == []


# ─────────────────────────────────────────────────────────────
#  _sort_rows_for_export
# ─────────────────────────────────────────────────────────────
def _export_rows():
    return [
        {"datetime_raw": 300, "client": "beta"},
        {"datetime_raw": 100, "client": "Alpha"},
        {"datetime_raw": 200, "client": "gamma"},
    ]


def test_sort_rows_for_export_no_sort_col_keeps_order_and_does_not_mutate():
    rows = _export_rows()
    original = list(rows)
    out = app._sort_rows_for_export(rows, None, -1)
    assert out == original
    assert rows == original
    assert out is not rows


def test_sort_rows_for_export_datetime_ascending_uses_raw_not_string():
    rows = _export_rows()
    out = app._sort_rows_for_export(rows, "datetime", 1)
    assert [r["datetime_raw"] for r in out] == [100, 200, 300]


def test_sort_rows_for_export_datetime_descending():
    rows = _export_rows()
    out = app._sort_rows_for_export(rows, "datetime", -1)
    assert [r["datetime_raw"] for r in out] == [300, 200, 100]


def test_sort_rows_for_export_text_column_case_insensitive_ascending():
    rows = _export_rows()
    out = app._sort_rows_for_export(rows, "client", 1)
    assert [r["client"] for r in out] == ["Alpha", "beta", "gamma"]


def test_sort_rows_for_export_text_column_case_insensitive_descending():
    rows = _export_rows()
    out = app._sort_rows_for_export(rows, "client", -1)
    assert [r["client"] for r in out] == ["gamma", "beta", "Alpha"]


def test_sort_rows_for_export_missing_sort_key_does_not_raise():
    rows = [{"other": 1}, {"other": 2}]
    out = app._sort_rows_for_export(rows, "client", 1)
    assert len(out) == 2


def test_sort_rows_for_export_datetime_raw_none_or_non_numeric_does_not_raise():
    rows = [
        {"datetime_raw": None, "client": "a"},
        {"datetime_raw": "not-a-number", "client": "b"},
        {"datetime_raw": 50, "client": "c"},
    ]
    out = app._sort_rows_for_export(rows, "datetime", 1)
    assert [r["client"] for r in out] == ["a", "b", "c"]


def test_sort_rows_for_export_unknown_sort_col_returns_rows_unchanged():
    rows = _export_rows()
    original = list(rows)
    out = app._sort_rows_for_export(rows, "not_a_real_column", 1)
    assert out == original


def test_sort_rows_for_export_sort_dir_as_float_or_numeric_string():
    rows = _export_rows()
    expected_asc = [r["datetime_raw"] for r in app._sort_rows_for_export(rows, "datetime", 1)]
    expected_desc = [r["datetime_raw"] for r in app._sort_rows_for_export(rows, "datetime", -1)]

    out_float_asc = app._sort_rows_for_export(rows, "datetime", 1.0)
    out_float_desc = app._sort_rows_for_export(rows, "datetime", -1.0)
    out_str_asc = app._sort_rows_for_export(rows, "datetime", "1")
    out_str_desc = app._sort_rows_for_export(rows, "datetime", "-1")

    assert [r["datetime_raw"] for r in out_float_asc] == expected_asc
    assert [r["datetime_raw"] for r in out_float_desc] == expected_desc
    assert [r["datetime_raw"] for r in out_str_asc] == expected_asc
    assert [r["datetime_raw"] for r in out_str_desc] == expected_desc
