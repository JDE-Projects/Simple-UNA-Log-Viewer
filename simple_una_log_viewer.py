"""
Simple UNA Log Viewer
A standalone desktop tool to view, filter, and export connection/event logs
from a UniFi Network Application controller, by site, time range, category,
and event type, with CSV export.

Read-only: makes no changes to the controller, sites, or device state.
Backend: urllib (standard library). Window: pywebview on the Qt backend,
UI in simple_una_log_viewer-UI.html.

Built with AI assistance, directed by JDE-Projects.
"""

import os
import sys
import ssl
import csv
import json
import time
import threading
import traceback
from datetime import datetime
from urllib.request import Request, HTTPCookieProcessor, build_opener, HTTPSHandler
from urllib.error import URLError, HTTPError
from http.cookiejar import CookieJar

import webview


# ─────────────────────────────────────────────────────────────
#  Paths (PyInstaller-aware)
# ─────────────────────────────────────────────────────────────
def resource_path(rel):
    """Path to a bundled resource (UI html, png, fonts), dev or frozen."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def exe_dir():
    """Folder the user sees: next to the exe when frozen, else next to .py."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ─────────────────────────────────────────────────────────────
#  Optional debug log (toggled in-app, OFF by default)
#  Writes Debug_Log_MMDDYYYY_HHMMSS.txt next to the exe; credentials
#  redacted. Off => writes nothing (read-only tool stays read-only).
# ─────────────────────────────────────────────────────────────
class DebugLog:
    def __init__(self):
        self._enabled = False
        self._path = None
        self._lock = threading.Lock()

    def set_enabled(self, on):
        with self._lock:
            on = bool(on)
            if on and not self._path:
                stamp = datetime.now().strftime("%m%d%Y_%H%M%S")
                self._path = os.path.join(exe_dir(), f"Debug_Log_{stamp}.txt")
                try:
                    with open(self._path, "w", encoding="utf-8") as f:
                        f.write("=== Simple UNA Log Viewer debug log ===\n")
                        f.write(f"Started: {datetime.now().isoformat()}\n")
                        f.write("=" * 60 + "\n\n")
                except Exception:
                    self._path = None
                    self._enabled = False
                    return False
            self._enabled = on
            return True

    def is_enabled(self):
        return self._enabled

    def log(self, label, content=""):
        if not self._enabled or not self._path:
            return
        try:
            with self._lock:
                with open(self._path, "a", encoding="utf-8") as f:
                    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    f.write(f"[{ts}] {label}\n")
                    if content:
                        if isinstance(content, (dict, list)):
                            content = json.dumps(content, indent=2, default=str)
                        f.write(f"{content}\n")
                    f.write("\n")
        except Exception:
            pass


debug = DebugLog()


def redact_payload(payload):
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    for k in ("password", "passwd", "x_password"):
        if k in out:
            out[k] = "***REDACTED***"
    return out


# ─────────────────────────────────────────────────────────────
#  Timezone label (for column header + CSV)
# ─────────────────────────────────────────────────────────────
def detect_local_tz_label():
    try:
        now = datetime.now().astimezone()
        tz_name = now.tzname() or ""
        if tz_name and len(tz_name) <= 5 and tz_name.replace(" ", "").isalpha():
            return tz_name.upper()
        if tz_name and " " in tz_name:
            initials = "".join(w[0] for w in tz_name.split() if w)
            if initials and initials.isalpha() and len(initials) <= 5:
                return initials.upper()
        offset = now.utcoffset()
        if offset is not None:
            total_min = int(offset.total_seconds() // 60)
            sign = "+" if total_min >= 0 else "-"
            total_min = abs(total_min)
            return f"UTC{sign}{total_min // 60:02d}:{total_min % 60:02d}"
        return "local"
    except Exception:
        return "local"


LOCAL_TZ_LABEL = detect_local_tz_label()


# ─────────────────────────────────────────────────────────────
#  Static option sets (single source of truth, sent to the UI)
# ─────────────────────────────────────────────────────────────
TIME_RANGES = [("1 Hour", 1), ("1 Day", 24), ("1 Week", 168), ("1 Month", 720)]
DEFAULT_TIME_RANGE = "1 Day"

LOG_TYPES = ["General", "Audit"]
DEFAULT_LOG_TYPE = "General"

CATEGORIES = {
    "Client Devices":       "CLIENT_DEVICES",
    "Internet and WAN":     "INTERNET_AND_WAN",
    "Power":                "POWER",
    "Security":             "SECURITY",
    "Software Updates":     "SOFTWARE_UPDATES",
    "UniFi Devices":        "UNIFI_DEVICES",
    "UniFi Ethernet Ports": "UNIFI_ETHERNET_PORTS",
    "VPN":                  "VPN",
}
CATEGORY_ENUM_TO_LABEL = {v: k for k, v in CATEGORIES.items()}

ALL_SEVERITIES = ["INFO", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"]

EVENT_KEYS = {
    "WiFi Client Connected":     "CLIENT_CONNECTED_WIRELESS_2",
    "WiFi Client Disconnected":  "CLIENT_DISCONNECTED_WIRELESS_2",
    "WiFi Client Roamed":        "CLIENT_ROAMED_2",
    "Wired Client Connected":    "CLIENT_CONNECTED_WIRED_2",
    "Wired Client Disconnected": "CLIENT_DISCONNECTED_WIRED_2",
}
KEY_TO_EVENT_LABEL = {v: k for k, v in EVENT_KEYS.items()}


# ─────────────────────────────────────────────────────────────
#  JS-facing API
# ─────────────────────────────────────────────────────────────
class Api:
    def __init__(self):
        self._window = None
        self.connected = False
        self.opener = None
        self.cookie_jar = None
        self.ssl_ctx = None
        self.sites = []
        self.controller_url = ""
        self._cred_user = ""
        self._cred_pass = ""
        self._opener_lock = threading.Lock()
        self._reauth_lock = threading.Lock()
        self._keepalive_timer = None
        self._last_rows = []          # rows from the most recent search (for export)

    def set_window(self, window):
        self._window = window

    # ---- metadata for building the UI controls ----
    def get_meta(self):
        return {
            "tz": LOCAL_TZ_LABEL,
            "time_ranges": [lbl for lbl, _ in TIME_RANGES],
            "default_time_range": DEFAULT_TIME_RANGE,
            "log_types": LOG_TYPES,
            "default_log_type": DEFAULT_LOG_TYPE,
            "categories": list(CATEGORIES.keys()),
            "events": list(EVENT_KEYS.keys()),
        }

    # ---- debug toggle ----
    def set_debug(self, enabled):
        ok = debug.set_enabled(enabled)
        debug.log("Debug logging enabled" if enabled and ok else "Debug logging disabled")
        return {"ok": ok, "enabled": debug.is_enabled()}

    # ---- connection ----
    def _create_opener(self):
        self.ssl_ctx = ssl.create_default_context()
        self.ssl_ctx.check_hostname = False
        self.ssl_ctx.verify_mode = ssl.CERT_NONE
        self.cookie_jar = CookieJar()
        self.opener = build_opener(HTTPSHandler(context=self.ssl_ctx),
                                   HTTPCookieProcessor(self.cookie_jar))

    def _do_login(self):
        self._create_opener()
        login_url = f"{self.controller_url}/api/login"
        debug.log(f"LOGIN -> POST {login_url}",
                  f"username: {self._cred_user}\npassword: ***REDACTED***")
        body = json.dumps({"username": self._cred_user,
                           "password": self._cred_pass}).encode("utf-8")
        req = Request(login_url, data=body, headers={"Content-Type": "application/json"})
        resp = self.opener.open(req)
        debug.log(f"LOGIN <- {resp.getcode()}")
        return resp.getcode() == 200

    def _safe_reauth(self):
        with self._reauth_lock:
            self._do_login()

    def _api_request(self, path, method="GET", data=None, retry=True):
        url = f"{self.controller_url}{path}"
        rm = "POST" if (data is not None or method == "POST") else "GET"
        debug.log(f"REQUEST -> {rm} {url}", redact_payload(data) if data else "(no body)")
        try:
            with self._opener_lock:
                if data is not None:
                    req = Request(url, data=json.dumps(data).encode("utf-8"),
                                  headers={"Content-Type": "application/json"})
                else:
                    req = Request(url)
                if method == "POST" and data is None:
                    req.data = b""
                    req.add_header("Content-Type", "application/json")
                    req.get_method = lambda: "POST"
                elif method == "POST" and data is not None:
                    req.get_method = lambda: "POST"
                resp = self.opener.open(req)
                code = resp.getcode()
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw)
                meta = parsed.get("meta", {}) if isinstance(parsed, dict) else {}
                rc = meta.get("rc", "?")
                df = parsed.get("data", []) if isinstance(parsed, dict) else []
                dc = len(df) if isinstance(df, list) else "n/a"
                debug.log(f"RESPONSE <- {url}",
                          f"HTTP {code} | meta.rc={rc} | data items: {dc}")
                if rc != "ok" or dc == 0:
                    debug.log(f"RAW BODY (first 2000) for {url}", raw[:2000])
                return parsed
        except HTTPError as e:
            err = ""
            try:
                err = e.read().decode("utf-8")[:2000]
            except Exception:
                pass
            debug.log(f"HTTPError {e.code} on {url}", f"{e.reason}\n{err}")
            if e.code == 401 and retry:
                self._safe_reauth()
                return self._api_request(path, method, data, retry=False)
            raise
        except (URLError, OSError) as e:
            debug.log(f"URLError/OSError on {url}", str(e))
            if retry:
                self._safe_reauth()
                return self._api_request(path, method, data, retry=False)
            raise
        except Exception as e:
            debug.log(f"UNEXPECTED on {url}", f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            raise

    def connect(self, url, user, pwd):
        url = (url or "").strip().rstrip("/")
        user = (user or "").strip()
        pwd = (pwd or "").strip()
        if not url or not user or not pwd:
            return {"ok": False, "error": "Please fill in all connection fields."}
        self.controller_url = url
        self._cred_user = user
        self._cred_pass = pwd
        debug.log("=" * 60)
        debug.log("CONNECT requested", {"url": url, "user": user})
        try:
            self._do_login()
            data = self._api_request("/api/self/sites")
            self.sites = data.get("data", []) if isinstance(data, dict) else []
            self.connected = True
            self._start_keepalive()
            sites = [{"id": s.get("name", ""),
                      "label": (s.get("desc") or s.get("name") or "Unknown")}
                     for s in self.sites]
            return {"ok": True, "sites": sites}
        except Exception as e:
            self.connected = False
            debug.log("CONNECT failed", str(e))
            return {"ok": False, "error": str(e)}

    def disconnect(self):
        self._stop_keepalive()
        if self.opener and self.controller_url:
            try:
                req = Request(f"{self.controller_url}/api/logout", data=b"",
                              headers={"Content-Type": "application/json"})
                req.get_method = lambda: "POST"
                self.opener.open(req)
            except Exception:
                pass
        self.connected = False
        self.sites = []
        self.opener = None
        self.cookie_jar = None
        self._cred_pass = ""
        self._last_rows = []
        debug.log("DISCONNECTED")
        return {"ok": True}

    # ---- keepalive ----
    def _start_keepalive(self):
        self._stop_keepalive()
        self._keepalive_timer = threading.Timer(300, self._keepalive_tick)
        self._keepalive_timer.daemon = True
        self._keepalive_timer.start()

    def _stop_keepalive(self):
        if self._keepalive_timer:
            self._keepalive_timer.cancel()
            self._keepalive_timer = None

    def _keepalive_tick(self):
        if self.connected:
            try:
                self._api_request("/api/self/sites")
            except Exception:
                pass
            self._start_keepalive()

    # ---- search ----
    def _progress(self, count):
        if self._window:
            try:
                self._window.evaluate_js(f"window.onSearchProgress && window.onSearchProgress({count})")
            except Exception:
                pass

    def run_search(self, site_id, time_range_label, log_type, event_keys, categories):
        if not self.connected:
            return {"ok": False, "error": "Not connected."}
        site = next((s for s in self.sites if s.get("name") == site_id), None)
        if not site:
            return {"ok": False, "error": "Select a site before running a search."}

        hours = next((h for lbl, h in TIME_RANGES if lbl == time_range_label), 24)
        categories_enum = [CATEGORIES[c] for c in (categories or []) if c in CATEGORIES]
        ekeys = [EVENT_KEYS[e] for e in (event_keys or []) if e in EVENT_KEYS]

        debug.log("SEARCH initiated", {
            "site": site.get("desc") or site.get("name"),
            "hours": hours, "log_type": log_type,
            "event_keys": ekeys, "categories": categories_enum,
        })
        try:
            rows, had_error = self._query_site_events(site, hours, log_type, categories_enum)
            total = len(rows)
            filtered = self._filter_rows(rows, ekeys, categories_enum)
            filtered.sort(key=lambda r: r.get("datetime_raw", 0), reverse=True)
            self._last_rows = filtered
            debug.log("SEARCH complete",
                      {"raw": total, "filtered": len(filtered), "had_error": had_error})
            return {"ok": True, "rows": filtered, "total": total, "had_error": had_error}
        except Exception as e:
            debug.log("SEARCH exception", traceback.format_exc())
            return {"ok": False, "error": str(e)}

    def _query_site_events(self, site, hours, log_type, categories_enum):
        site_name = site.get("name", "")
        site_desc = site.get("desc", site_name)
        rows = []
        now_ms = int(time.time() * 1000)
        from_ms = now_ms - (hours * 3600 * 1000)
        path_segment = "admin" if log_type == "Audit" else "all"
        payload_categories = list(categories_enum) if categories_enum else list(set(CATEGORIES.values()))
        try:
            page_number, page_size, all_items = 0, 1000, []
            while True:
                payload = {
                    "severities":    list(ALL_SEVERITIES),
                    "timestampFrom": from_ms,
                    "timestampTo":   now_ms,
                    "categories":    payload_categories,
                    "pageNumber":    page_number,
                    "pageSize":      page_size,
                }
                resp = self._api_request(
                    f"/v2/api/site/{site_name}/system-log/{path_segment}",
                    method="POST", data=payload)
                if isinstance(resp, dict):
                    batch = resp.get("data", [])
                    batch = batch if isinstance(batch, list) else []
                elif isinstance(resp, list):
                    batch = resp
                else:
                    batch = []
                all_items.extend(batch)
                if len(batch) < page_size:
                    break
                page_number += 1
                if page_number >= 50:
                    break
                self._progress(len(all_items))
            for item in all_items:
                rows.append(self._build_event_row(item, site_desc, site_name))
            return rows, False
        except Exception:
            debug.log("EXCEPTION in _query_site_events", traceback.format_exc())
            return rows, True

    def _render_message(self, template, params):
        if not template or not isinstance(params, dict):
            return template or ""
        try:
            import re
            def _replace(m):
                sub = params.get(m.group(1))
                return str(sub.get("name", m.group(0))) if isinstance(sub, dict) else m.group(0)
            return re.sub(r"\{([A-Z_]+)\}", _replace, template)
        except Exception:
            return template

    def _build_event_row(self, item, site_desc, site_name):
        time_ms = item.get("timestamp", 0)
        try:
            time_ms = int(time_ms)
        except (TypeError, ValueError):
            time_ms = 0
        try:
            datetime_str = datetime.fromtimestamp(time_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError, OSError):
            datetime_str = ""

        key = item.get("key") or item.get("event") or ""
        event_label = item.get("title_raw") or KEY_TO_EVENT_LABEL.get(key, key)
        category_enum = item.get("category", "")
        category = CATEGORY_ENUM_TO_LABEL.get(category_enum, category_enum or "Other")
        severity = item.get("severity", "")

        params = item.get("parameters") or {}
        if not isinstance(params, dict):
            params = {}

        def _p(name, field="name"):
            sub = params.get(name)
            return (sub.get(field, "") or "") if isinstance(sub, dict) else ""

        client_param = params.get("CLIENT") if isinstance(params.get("CLIENT"), dict) else {}
        client = (client_param.get("hostname", "") or client_param.get("name", "")) if client_param else ""
        mac = client_param.get("id", "") if client_param else ""
        ap_name = _p("DEVICE") or _p("DEVICE_WITH_PORT")
        ssid = _p("WLAN")
        network = _p("NETWORK")
        description = self._render_message(item.get("message_raw", ""), params) or item.get("title_raw", "")

        return {
            "datetime": datetime_str, "datetime_raw": time_ms,
            "site": site_desc, "site_id": site_name,
            "category": category, "category_enum": category_enum,
            "event": event_label, "event_key": key,
            "severity": severity, "description": description,
            "client": client, "mac": mac, "ap": ap_name,
            "ssid": ssid, "network": network,
        }

    def _filter_rows(self, rows, event_keys, categories_enum):
        if not event_keys and not categories_enum:
            return rows
        out = []
        for r in rows:
            if event_keys and r["event_key"] not in event_keys:
                continue
            if categories_enum and r["category_enum"] not in categories_enum:
                continue
            out.append(r)
        return out

    # ---- CSV export ----
    def export_csv(self, rows):
        rows = rows or self._last_rows
        if not rows:
            return {"ok": False, "error": "Nothing to export."}
        if not self._window:
            return {"ok": False, "error": "No window."}
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG, save_filename="una_log_export.csv",
            file_types=("CSV file (*.csv)", "All files (*.*)"))
        if not result:
            return {"ok": False, "cancelled": True}
        path = result if isinstance(result, str) else result[0]
        if not path.lower().endswith(".csv"):
            path += ".csv"
        columns = [
            ("datetime", f"datetime_{LOCAL_TZ_LABEL}"), ("site", "site"),
            ("category", "category"), ("event", "event"), ("severity", "severity"),
            ("description", "description"), ("client", "client"), ("mac", "mac"),
            ("ap", "ap"), ("ssid", "ssid"), ("network", "network"),
        ]
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([h for _, h in columns])
                for r in rows:
                    w.writerow([r.get(k, "") for k, _ in columns])
            debug.log("EXPORT", f"{len(rows)} rows -> {path}")
            return {"ok": True, "path": path, "count": len(rows)}
        except Exception as e:
            return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────
#  Splash handling (guarded; 5s floor, close on ready, watchdog)
# ─────────────────────────────────────────────────────────────
try:
    import pyi_splash  # type: ignore
    HAS_SPLASH = True
except Exception:
    HAS_SPLASH = False

_splash_closed = threading.Lock()
_splash_done = False
_start_time = time.time()


def _close_splash():
    global _splash_done
    with _splash_closed:
        if _splash_done:
            return
        _splash_done = True
    if HAS_SPLASH:
        try:
            pyi_splash.close()
        except Exception:
            pass


def _on_loaded():
    elapsed = time.time() - _start_time
    delay = max(0.0, 5.0 - elapsed)   # keep splash up at least 5s
    threading.Timer(delay, _close_splash).start()


def main():
    if HAS_SPLASH:
        threading.Timer(30.0, _close_splash).start()   # watchdog ceiling

    # Windows taskbar identity, so the taskbar shows our icon (not Python/Qt)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "JDEProjects.SimpleUNALogViewer")
        except Exception:
            pass

    api = Api()
    window = webview.create_window(
        "Simple UNA Log Viewer",
        url=resource_path("simple_una_log_viewer-UI.html"),
        js_api=api,
        width=1400, height=850, min_size=(1100, 700),
        background_color="#0a0e14",
    )
    api.set_window(window)
    window.events.loaded += _on_loaded

    try:
        webview.start(gui="qt", icon=resource_path("simple_una_log_viewer.png"))
    except TypeError:
        # Older pywebview without the icon kwarg
        webview.start(gui="qt")


if __name__ == "__main__":
    main()
