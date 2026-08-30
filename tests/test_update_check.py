"""Network-free coverage for the update-check error message helper."""

import errno
import io
import json
import socket
import ssl
import urllib.error

import pytest

import simple_una_log_viewer as app


def _http_error(code):
    return urllib.error.HTTPError("https://api.github.com", code, "error", None, None)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (_http_error(403), "GitHub is rate-limiting update checks from this network. Try again later."),
        (_http_error(404), "No published release was found."),
        (_http_error(503), "GitHub is having trouble on its end (HTTP 503)."),
        (_http_error(418), "GitHub returned an error (HTTP 418)."),
        (json.JSONDecodeError("bad JSON", "x", 0), "GitHub returned something unexpected. This often means a proxy or a guest wifi sign-in page answered instead."),
        (urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate")), "GitHub's certificate could not be verified. This usually means antivirus or a network filter is inspecting HTTPS traffic."),
        (urllib.error.URLError(ssl.SSLEOFError(8, "eof")), "The secure connection was cut off during the handshake with GitHub."),
        (urllib.error.URLError(ssl.SSLError(1, "ssl")), "The secure connection to GitHub failed."),
        (urllib.error.URLError(socket.gaierror(-2, "not found")), "The address for api.github.com could not be looked up. Check DNS or the internet connection."),
        (urllib.error.URLError(socket.timeout("timed out")), "GitHub didn't respond in time."),
        (urllib.error.URLError(ConnectionRefusedError("refused")), "The connection was refused or reset. A firewall or proxy may be blocking it."),
        (urllib.error.URLError(OSError(errno.ENETUNREACH, "unreachable")), "No network connection."),
        (urllib.error.URLError("unknown failure"), "Couldn't reach GitHub. Check the internet connection."),
    ],
)
def test_update_error_reason_known_failures(exc, expected):
    assert app._update_error_reason(exc) == expected


def test_update_error_reason_truncates_unknown_exception():
    reason = app._update_error_reason(RuntimeError("x" * 200))

    assert reason == "RuntimeError: " + "x" * 103 + "..."
    assert len(reason) == 120


_MAJOR, _MINOR, _PATCH = map(int, app.APP_VERSION.split("."))
_NEWER = f"{_MAJOR}.{_MINOR}.{_PATCH + 1}"


@pytest.mark.parametrize(
    ("latest", "expected_update"),
    [
        (_NEWER, True),
        (app.APP_VERSION, False),
    ],
)
def test_check_update_handles_release_response(monkeypatch, latest, expected_update):
    monkeypatch.setattr(
        app,
        "urlopen",
        lambda request, timeout: io.BytesIO(
            json.dumps({"tag_name": f"v{latest}"}).encode("utf-8")
        ),
    )

    result = app.Api().check_update()

    assert result == {
        "current": app.APP_VERSION,
        "version": latest,
        "update": expected_update,
        "offline": False,
    }


def test_check_update_rejects_non_object_json(monkeypatch):
    monkeypatch.setattr(
        app,
        "urlopen",
        lambda request, timeout: io.BytesIO(b"[]"),
    )

    result = app.Api().check_update()

    assert result == {
        "current": app.APP_VERSION,
        "version": None,
        "update": False,
        "offline": True,
        "reason": (
            "GitHub returned something unexpected. This often means a proxy "
            "or a guest wifi sign-in page answered instead."
        ),
    }
