#!/usr/bin/env python3
"""Regenerate screenshots/una-log-light-dark.png from the real desktop UI.

The generator serves only a temporary copy of the HTML, icon, and bundled
fonts. It injects fabricated scene data into the page's existing UI seams, so
no running controller, credentials, or working-copy files are needed.
"""

import argparse
import http.server
import json
import os
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scene  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
OUT_IMAGE = os.path.join(REPO_ROOT, "screenshots", "una-log-light-dark.png")
LAYOUT_WIDTH = 1800
LAYOUT_HEIGHT = 1120
CAPTURE_SCALE = 0.5


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def parse_app_version(source: str) -> str:
    """Return the source-of-record version or fail clearly when it is absent."""
    match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', source, re.MULTILINE)
    if not match:
        raise ValueError("could not find APP_VERSION assignment")
    return match.group(1)


def read_app_version() -> str:
    path = os.path.join(REPO_ROOT, "simple_una_log_viewer.py")
    try:
        with open(path, encoding="utf-8") as source_file:
            return parse_app_version(source_file.read())
    except OSError as exc:
        fail(f"could not read {path}: {exc}")
    except ValueError as exc:
        fail(f"{exc} in {path}")


def stage_ui(temp_dir: str) -> None:
    """Copy exactly the browser assets needed by the UI into temp_dir."""
    assets = (
        ("simple_una_log_viewer-UI.html", "index.html"),
        ("simple_una_log_viewer.png", "simple_una_log_viewer.png"),
    )
    for source_name, destination_name in assets:
        source = os.path.join(REPO_ROOT, source_name)
        if not os.path.isfile(source):
            fail(f"missing required UI asset: {source}")
        shutil.copy2(source, os.path.join(temp_dir, destination_name))

    fonts = os.path.join(REPO_ROOT, "fonts")
    if not os.path.isdir(fonts):
        fail(f"missing required fonts directory: {fonts}")
    shutil.copytree(fonts, os.path.join(temp_dir, "fonts"))


def build_setup_script(version: str) -> str:
    """Seed the real UI globals and call the same rendering seams as boot()."""
    metadata = dict(scene.META, version=version)
    scene_json = json.dumps({"meta": metadata, "rows": scene.ROWS})
    return (
        f"const screenshotScene={scene_json};"
        "META=screenshotScene.meta;rows=screenshotScene.rows;connected=true;"
        "sortCol='datetime';sortDir=-1;"
        "if(typeof buildSeg==='function'){"
        "buildSeg('timeSeg',META.time_ranges,META.default_time_range);"
        "buildSeg('typeSeg',META.log_types,META.default_log_type);"
        "}"
        "if(typeof buildChips==='function'){"
        "buildChips('catChips',META.categories);buildChips('evtChips',META.events);"
        "}"
        "if(typeof buildHead==='function')buildHead();"
        "if(typeof setConn==='function')setConn('live','Connected - 1 site');"
        "if(typeof $==='function'){"
        "const site=$('site');site.disabled=false;site.innerHTML='';"
        "const option=document.createElement('option');option.value=META.site.id;"
        "option.textContent=META.site.label;site.appendChild(option);"
        "$('url').value=META.controller_url;$('url').disabled=true;"
        "$('user').value=META.user;$('user').disabled=true;$('pass').disabled=true;"
        "$('connBtn').textContent='Disconnect';$('connBtn').className='btn-danger';"
        "$('searchBtn').disabled=false;$('exportBtn').disabled=false;"
        "$('statusText').textContent='Search completed';"
        "$('countText').textContent=rows.length+' event(s)';"
        "$('verText').textContent='v'+META.version;"
        "['Client Devices','UniFi Ethernet Ports'].forEach(label=>{const chip=[...$('catChips').children]"
        ".find(item=>item.dataset.label===label);if(chip)chip.classList.add('on');});"
        "['WiFi Client Connected','Wired Client Disconnected'].forEach(label=>{"
        "const chip=[...$('evtChips').children].find(item=>item.dataset.label===label);"
        "if(chip)chip.classList.add('on');});"
        "}"
        "if(typeof render==='function')render();"
    )


def build_capture_config(port: int, version: str) -> dict:
    return {
        "url": f"http://127.0.0.1:{port}/index.html",
        "width": LAYOUT_WIDTH,
        "height": LAYOUT_HEIGHT,
        "scale": CAPTURE_SCALE,
        "outDir": "shots",
        "waitFor": "typeof render === 'function'",
        "setup": build_setup_script(version),
        "settleMs": 500,
        "shots": [
            {"name": "dark", "script": "applyTheme('dark')"},
            {"name": "light", "script": "applyTheme('light')"},
        ],
    }


def write_capture_config(temp_dir: str, port: int, version: str) -> str:
    path = os.path.join(temp_dir, "shots.json")
    with open(path, "w", encoding="utf-8") as config_file:
        json.dump(build_capture_config(port, version), config_file, indent=2)
    return path


def run(command: list[str], label: str) -> None:
    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        fail(f"{label} failed with exit code {result.returncode}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="keep staged files for inspection")
    parser.add_argument(
        "--build-tools",
        help="path to Build-Tools (default: sibling build-tools directory)",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> None:
    args = parse_args(argv)
    build_tools = args.build_tools or os.path.join(os.path.dirname(REPO_ROOT), "build-tools")
    capture_script = os.path.join(build_tools, "screenshot", "capture.mjs")
    compose_script = os.path.join(build_tools, "screenshot", "compose.py")
    for path in (capture_script, compose_script):
        if not os.path.isfile(path):
            fail(f"missing {path}. Pass --build-tools with the Build-Tools path.")

    version = read_app_version()
    temp_dir = tempfile.mkdtemp(prefix="una-log-screenshot-")
    httpd = None
    try:
        stage_ui(temp_dir)
        port = free_port()

        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=temp_dir, **kwargs)

        httpd = socketserver.TCPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        config_path = write_capture_config(temp_dir, port, version)
        run(["node", capture_script, config_path], "capture")
        shots_dir = os.path.join(temp_dir, "shots")
        run(
            [
                sys.executable,
                compose_script,
                OUT_IMAGE,
                os.path.join(shots_dir, "dark.png"),
                os.path.join(shots_dir, "light.png"),
            ],
            "compose",
        )
    finally:
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if args.keep:
            print(f"temp folder kept at {temp_dir}")
        else:
            shutil.rmtree(temp_dir, ignore_errors=True)
            if os.path.exists(temp_dir):
                print(f"WARNING: could not remove {temp_dir}", file=sys.stderr)

    print(f"seeded version: v{version}")
    print(f"updated {OUT_IMAGE}")


if __name__ == "__main__":
    main(sys.argv[1:])
