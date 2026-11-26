#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Captures 4 consecutive PNG screenshots of `outputs/walkthrough_report.html`
served via an ephemeral loopback HTTP server so headless Chrome/Edge renders query params instantly.
"""
from __future__ import annotations

import functools
import http.server
import pathlib
import subprocess
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUTPUTS_DIR = ROOT / "outputs"
HTML_FILE = OUTPUTS_DIR / "walkthrough_report.html"
SHOTS_DIR = OUTPUTS_DIR / "screenshots"

BROWSER_CANDIDATES = [
    pathlib.Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    pathlib.Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    pathlib.Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]

SHOTS = [
    ("01_input_and_skill.png", "?sample=0&tab=1", "1440,1040"),
    ("02_changeradar_ast_trace.png", "?sample=0&tab=2", "1440,1080"),
    ("03_spark_raw_inference.png", "?sample=0&tab=3", "1440,1120"),
    ("04_verification_and_audit.png", "?sample=0&tab=4&demo_decisions=1", "1440,1260"),
]


def find_browser() -> pathlib.Path:
    for p in BROWSER_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError("Neither Chrome nor Edge found on system.")


def capture_all(html_path: pathlib.Path = HTML_FILE, out_dir: pathlib.Path = SHOTS_DIR) -> list[pathlib.Path]:
    if not html_path.exists():
        raise FileNotFoundError(f"HTML report not found: {html_path}")
    browser = find_browser()
    out_dir.mkdir(parents=True, exist_ok=True)

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(html_path.parent))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    srv_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    srv_thread.start()

    created: list[pathlib.Path] = []
    try:
        with tempfile.TemporaryDirectory(prefix="rg_headless_", ignore_cleanup_errors=True) as profile_dir:
            for fname, query, win_size in SHOTS:
                dest = out_dir / fname
                dest.unlink(missing_ok=True)
                target_url = f"http://127.0.0.1:{port}/{html_path.name}{query}"
                cmd = [
                    str(browser),
                    "--headless",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-extensions",
                    "--hide-scrollbars",
                    f"--user-data-dir={profile_dir}",
                    f"--window-size={win_size}",
                    f"--screenshot={dest}",
                    target_url,
                ]
                try:
                    subprocess.run(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=35,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    pass
                if not dest.exists() or dest.stat().st_size < 5000:
                    raise RuntimeError(f"Screenshot failed or empty: {dest}")
                print(f"Captured {dest.name} ({dest.stat().st_size / 1024:.1f} KiB)")
                created.append(dest)
    finally:
        httpd.shutdown()
        httpd.server_close()

    return created


if __name__ == "__main__":
    capture_all()
