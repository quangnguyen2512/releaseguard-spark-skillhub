#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resilient live local Vulkan `llama-server.exe` (`Intel UHD Graphics`, `-ngl 99`) runner
for `Spark-X2.6-4B-Q4_K_M.gguf` across all 5 OSS samples (`S01`–`S05`).

Disables cross-request LCP slot cache shifting (`--cache-ram 0` + `cache_prompt: false`)
to avoid Vulkan hybrid sliding/full attention slot-shift resets, and runs sample-by-sample
with `--resume` before generating the final full 5-sample bundle and 4 PNG screenshots.
"""
from __future__ import annotations

import ctypes
import json
import pathlib
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import capture_screenshots  # noqa: E402
import run_challenge  # noqa: E402

VK_SERVER_EXE = ROOT / "bin" / "llama_vk" / "llama-server.exe"
CPU_SERVER_EXE = ROOT / "bin" / "llama" / "llama-server.exe"
MODEL_GGUF = ROOT / "models" / "Spark-X2.6-4B-Q4_K_M.gguf"
PORT = 18080
SAMPLE_PREFIXES = ["S01", "S02", "S03", "S04", "S05"]


def start_keepawake() -> threading.Event:
    stop_evt = threading.Event()
    if sys.platform != "win32":
        return stop_evt

    def _worker() -> None:
        flags = 0x80000000 | 0x00000001 | 0x00000002
        while not stop_evt.is_set():
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(flags)
            except Exception:
                pass
            stop_evt.wait(25.0)
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        except Exception:
            pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return stop_evt


def stop_own_llama_servers() -> None:
    if sys.platform == "win32":
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name LIKE '%llama%'\" | Where-Object { $_.ExecutablePath -like '*spark_x26_skillhub_100usd*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }",
            ],
            capture_output=True,
            text=True,
            check=False,
        )


def wait_for_health(port: int, proc: subprocess.Popen, log_path: pathlib.Path, timeout_sec: float = 240.0) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.time() + timeout_sec
    url = f"http://127.0.0.1:{port}/health"
    t0 = time.time()
    while time.time() < deadline:
        if proc.poll() is not None:
            tail = log_path.read_text(encoding="utf-8", errors="ignore")[-2000:] if log_path.exists() else ""
            raise RuntimeError(f"llama-server exited prematurely with code {proc.returncode}:\n{tail}")
        try:
            with opener.open(url, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "ok":
                    print(f"llama-server healthy on 127.0.0.1:{port} after {time.time() - t0:.1f}s: {data}", flush=True)
                    return
        except Exception:
            pass
        time.sleep(1.5)
    tail = log_path.read_text(encoding="utf-8", errors="ignore")[-2000:] if log_path.exists() else ""
    raise TimeoutError(f"llama-server did not become healthy within {timeout_sec}s:\n{tail}")


def launch_server(server_exe: pathlib.Path, use_vulkan: bool, help_text: str, log_path: pathlib.Path):
    cmd = [
        str(server_exe),
        "-m",
        str(MODEL_GGUF),
        "--alias",
        "Spark-X2.6-4B-Q4_K_M",
        "--host",
        "127.0.0.1",
        "--port",
        str(PORT),
        "-np",
        "1",
        "-c",
        "4096",
        "-t",
        "2",
        "-tb",
        "2",
        "--jinja",
    ]
    if use_vulkan:
        cmd.extend(["-ngl", "99"])
    else:
        cmd.extend(["-lm", "none"])
    if "--cache-ram" in help_text:
        cmd.extend(["--cache-ram", "0"])
    if "--no-warmup" in help_text:
        cmd.append("--no-warmup")
    if "--reasoning" in help_text:
        cmd.extend(["--reasoning", "off"])
    if "--reasoning-budget" in help_text:
        cmd.extend(["--reasoning-budget", "0"])
    if "--no-reasoning-preserve" in help_text:
        cmd.append("--no-reasoning-preserve")

    log_file = log_path.open("a", encoding="utf-8")
    print(f"Starting {'Vulkan GPU' if use_vulkan else 'CPU'} llama-server:", " ".join(cmd), flush=True)
    proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
    wait_for_health(PORT, proc, log_path, timeout_sec=240.0)
    return proc, log_file


def shutdown_server(proc: subprocess.Popen | None, log_file) -> None:
    if proc is not None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    if log_file is not None:
        log_file.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    server_exe = VK_SERVER_EXE if VK_SERVER_EXE.exists() else CPU_SERVER_EXE
    use_vulkan = server_exe == VK_SERVER_EXE
    help_proc = subprocess.run([str(server_exe), "--help"], capture_output=True, text=True, timeout=15, check=False)
    help_text = (help_proc.stdout or "") + (help_proc.stderr or "")

    log_path = ROOT / "outputs" / "llama_server_run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")

    keepawake_stop = start_keepawake()
    stop_own_llama_servers()

    proc = None
    log_file = None
    base_args = [
        "--download-and-run",
        "--backend",
        "openai-compat",
        "--api-base",
        f"http://127.0.0.1:{PORT}/v1",
        "--served-model-name",
        "Spark-X2.6-4B-Q4_K_M",
        "--thinking",
        "none",
        "--temperature",
        "0.0",
        "--max-tokens",
        "900",
        "--resume",
    ]

    try:
        proc, log_file = launch_server(server_exe, use_vulkan, help_text, log_path)
        for prefix in SAMPLE_PREFIXES:
            trace_matches = list((ROOT / "outputs" / "runs" / "real_spark_none").glob(f"{prefix}*/trace.json"))
            if trace_matches:
                print(f"Sample {prefix} already cached at {trace_matches[0].name}; skipping server call.", flush=True)
                continue

            for attempt in (1, 2):
                if proc is None or proc.poll() is not None:
                    shutdown_server(proc, log_file)
                    stop_own_llama_servers()
                    proc, log_file = launch_server(server_exe, use_vulkan, help_text, log_path)
                try:
                    rc = run_challenge.main([*base_args, "--sample", prefix])
                    if rc == 0:
                        break
                except Exception as exc:
                    print(f"Attempt {attempt} on {prefix} raised {exc!r}; restarting server...", flush=True)
                    shutdown_server(proc, log_file)
                    proc, log_file = None, None
                    if attempt == 2:
                        raise

        # Final assembly pass across all 5 cached real traces -> writes run_bundle.json, walkthrough_report.html, HF_DISCUSSION_FILLED.md
        print("\nAssembling full 5-sample real bundle + HTML walkthrough + HF Discussion document...", flush=True)
        rc = run_challenge.main(base_args)
        if rc != 0:
            return rc
    finally:
        print("Stopping local llama-server...", flush=True)
        shutdown_server(proc, log_file)
        stop_own_llama_servers()
        keepawake_stop.set()
        print("llama-server stopped cleanly.", flush=True)

    shots = capture_screenshots.capture_all()
    print("All 4 walkthrough screenshots captured:", [s.name for s in shots], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
