"""
Tests for the local prefs store (load_prefs / save_prefs) in
simple_una_log_viewer.py. The real prefs path is always redirected to a
tmp_path file via monkeypatch; the repo folder is never touched.
"""

import simple_una_log_viewer as app


def _redirect_pref_path(monkeypatch, tmp_path, name="test.pref"):
    path = tmp_path / name
    monkeypatch.setattr(app, "_pref_path", lambda: str(path))
    return path


def test_save_then_load_round_trip_preserves_all_keys(monkeypatch, tmp_path):
    _redirect_pref_path(monkeypatch, tmp_path)
    prefs = {"theme": "light", "window": {"x": 10, "y": 20, "width": 800, "height": 600}}
    assert app.save_prefs(prefs) is True
    loaded = app.load_prefs()
    assert loaded == prefs


def test_load_prefs_missing_file_returns_empty_dict(monkeypatch, tmp_path):
    _redirect_pref_path(monkeypatch, tmp_path, name="does-not-exist.pref")
    assert app.load_prefs() == {}


def test_load_prefs_corrupt_json_returns_empty_dict(monkeypatch, tmp_path):
    path = _redirect_pref_path(monkeypatch, tmp_path)
    path.write_text("{not valid json", encoding="utf-8")
    assert app.load_prefs() == {}


def test_load_prefs_json_list_returns_empty_dict(monkeypatch, tmp_path):
    path = _redirect_pref_path(monkeypatch, tmp_path)
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert app.load_prefs() == {}
