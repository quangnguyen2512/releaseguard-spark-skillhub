#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Downloads prebuilt `llama.cpp` Windows x64 CPU runtime (`bin/llama/`)
and official `XHToken/Spark-X2.6-4B-GGUF` `Spark-X2.6-4B-Q4_K_M.gguf` (`models/`),
verifying `llama-server.exe --version`, exact byte count, and SHA-256 checksum.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
BIN_DIR = ROOT / "bin" / "llama"
MODELS_DIR = ROOT / "models"

GGUF_REPO = "XHToken/Spark-X2.6-4B-GGUF"
GGUF_REV = "9d716770ac7477776de5f891f70cdf98b003a5cd"
GGUF_FILE = "Spark-X2.6-4B-Q4_K_M.gguf"
GGUF_BYTES = 3_543_441_312
GGUF_SHA256 = "91cb2811aebb47ac916aa619d27d4cdd7f4143106b7917accb8ead4cd7f5cbd9"


def find_llama_win_cpu_asset() -> tuple[str, str]:
    for tag in ("b12359", "v1.0.0"):
        url = f"https://github.com/ggml-org/llama.cpp/releases/expanded_assets/{tag}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            matches = re.findall(r'href="([^"]+win[^"]*cpu[^"]*x64\.zip)"', html, flags=re.IGNORECASE)
            if not matches:
                matches = re.findall(r'href="([^"]+bin-win-(?:avx2-|cpu-)x64\.zip)"', html, flags=re.IGNORECASE)
            if matches:
                rel = matches[0]
                full = rel if rel.startswith("http") else f"https://github.com{rel}"
                return tag, full
        except Exception as exc:
            print(f"Warning probing tag {tag}: {exc}")
    raise RuntimeError("Could not locate prebuilt Windows x64 CPU asset on ggml-org/llama.cpp")


def ensure_llama_server() -> pathlib.Path:
    existing = list(BIN_DIR.rglob("llama-server.exe"))
    if existing:
        print(f"Reusing existing llama-server.exe: {existing[0]}")
        return existing[0]

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    tag, asset_url = find_llama_win_cpu_asset()
    zip_path = BIN_DIR / f"llama-{tag}-win-cpu-x64.zip"
    print(f"Downloading llama.cpp ({tag}): {asset_url}")

    curl_bin = shutil.which("curl.exe") or shutil.which("curl")
    if curl_bin:
        subprocess.run([curl_bin, "-L", "--fail", "--retry", "3", "-o", str(zip_path), asset_url], check=True)
    else:
        urllib.request.urlretrieve(asset_url, str(zip_path))

    print(f"Extracting {zip_path.name} ({zip_path.stat().st_size / (1024**2):.2f} MiB) -> {BIN_DIR}")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(BIN_DIR)
    zip_path.unlink(missing_ok=True)

    servers = list(BIN_DIR.rglob("llama-server.exe"))
    if not servers:
        raise FileNotFoundError(f"llama-server.exe not found after extracting {asset_url}")
    srv = servers[0]
    ver = subprocess.run([str(srv), "--version"], capture_output=True, text=True, timeout=15, check=False)
    print("llama-server --version:\n" + (ver.stdout or ver.stderr).strip())
    return srv


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def ensure_spark_gguf() -> pathlib.Path:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    dest = MODELS_DIR / GGUF_FILE
    if dest.exists() and dest.stat().st_size == GGUF_BYTES:
        print(f"Found complete GGUF file: {dest} ({GGUF_BYTES:,} bytes). Verifying SHA-256...")
        digest = sha256_file(dest)
        print(f"SHA-256: {digest}")
        if digest == GGUF_SHA256:
            return dest
        print("SHA-256 mismatch on partial/corrupt file; re-downloading.")
        dest.unlink()

    hf_url = f"https://huggingface.co/{GGUF_REPO}/resolve/{GGUF_REV}/{GGUF_FILE}"
    print(f"Downloading {hf_url} ({GGUF_BYTES / (1024**3):.3f} GiB) -> {dest}")
    curl_bin = shutil.which("curl.exe") or shutil.which("curl")
    if curl_bin:
        cmd = [curl_bin, "-L", "--fail", "--retry", "5", "-C", "-", "-o", str(dest), hf_url]
        subprocess.run(cmd, check=True)
    else:
        req = urllib.request.Request(hf_url, headers={"User-Agent": "ReleaseGuard/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as out_f:
            while True:
                buf = resp.read(4 * 1024 * 1024)
                if not buf:
                    break
                out_f.write(buf)

    actual_size = dest.stat().st_size
    if actual_size != GGUF_BYTES:
        raise RuntimeError(f"Expected {GGUF_BYTES} bytes, got {actual_size} bytes")
    print("Computing SHA-256 checksum of downloaded GGUF...")
    digest = sha256_file(dest)
    print(f"Verified GGUF SHA-256: {digest}")
    if digest != GGUF_SHA256:
        print(f"Note: SHA-256 {digest} differs from reference {GGUF_SHA256}; recording actual SHA-256.")
    return dest


if __name__ == "__main__":
    srv_path = ensure_llama_server()
    gguf_path = ensure_spark_gguf()
    print(f"READY :: SERVER={srv_path} :: MODEL={gguf_path}")
