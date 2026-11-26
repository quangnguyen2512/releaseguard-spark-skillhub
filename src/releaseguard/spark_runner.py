# -*- coding: utf-8 -*-
"""Environment/Hardware Checker & Local `Spark-X2.6-4B` Inference Runners.

Honors Issue #32 rules strictly:
- Checks GPU (`nvidia-smi`), CPU, RAM, free disk space, and local Hugging Face / GGUF cache.
- Displays exact model revision SHAs and download sizes before fetching any missing weights,
  requiring explicit user confirmation.
- Supports BOTH:
  1. Local OpenAI-compatible server (`llama.cpp` `llama-server`, `vLLM`, `SGLang`, `Ollama`, `LM Studio`)
  2. Local Hugging Face `transformers` checkpoint (`XHToken/Spark-X2.6-4B`)
  3. Clearly watermarked `--dry-run` (`DRY_RUN_SYNTHETIC_PREVIEW`) for zero-weight pipeline testing.
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from releaseguard.models import ChangeradarResult, ReleaseSample

# Official XHToken Hugging Face metadata verified 2026-11-25
SPARK_HF_REPO = "XHToken/Spark-X2.6-4B"
SPARK_HF_REVISION = "64ca8f2a295b8ceb2757b9d4749a6558c4759e5b"
SPARK_HF_TOTAL_BYTES = 8_239_302_573  # 7.673 GiB (8.239 GB) across 5 safetensors shards

SPARK_GGUF_REPO = "XHToken/Spark-X2.6-4B-GGUF"
SPARK_GGUF_REVISION = "9d716770ac7477776de5f891f70cdf98b003a5cd"
SPARK_GGUF_Q4_FILENAME = "Spark-X2.6-4B-Q4_K_M.gguf"
SPARK_GGUF_Q4_BYTES = 3_543_441_312  # 3.300 GiB (3.543 GB)
SPARK_GGUF_Q8_FILENAME = "Spark-X2.6-4B-Q8_0.gguf"
SPARK_GGUF_Q8_BYTES = 4_375_021_824  # 4.075 GiB (4.375 GB)

SPARK_INT4_REPO = "XHToken/Spark-X2.6-4B-INT4"
SPARK_INT4_REVISION = "37db7af521b10e373e6f94060a290de0f5874d3c"
SPARK_INT4_BYTES = 3_411_522_856  # 3.177 GiB (3.412 GB)

DEFAULT_LOCAL_ENDPOINTS = (
    "http://127.0.0.1:18080/v1",
    "http://127.0.0.1:30000/v1",
    "http://127.0.0.1:11434/v1",
    "http://127.0.0.1:1234/v1",
)


def is_spark_model_list(models: list[str]) -> bool:
    """Return True only if at least one served model ID identifies as a Spark checkpoint."""
    return any("spark" in m.lower() for m in models)


@dataclass
class EnvironmentReport:
    os_platform: str
    python_version: str
    cpu_model: str
    logical_cores: int
    ram_total_gib: float
    nvidia_gpu: str | None
    disk_drive: str
    disk_total_gib: float
    disk_free_gib: float
    hf_cache_dir: str
    cached_spark_repos: list[str]
    local_gguf_files: list[str]
    active_local_servers: list[dict[str, Any]]
    recommended_runtime: str
    models_catalog: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InferenceResult:
    backend: str
    is_dry_run: bool
    model_id: str
    model_revision: str
    quantization_or_dtype: str
    thinking_mode: str
    raw_text: str
    latency_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None
    inference_settings: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _detect_ram_gib() -> float:
    if sys.platform == "win32":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return round(stat.ullTotalPhys / (1024**3), 2)
    elif Path("/proc/meminfo").exists():
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                kb = int(line.split()[1])
                return round(kb / (1024**2), 2)
    return 0.0


def _detect_cpu_model() -> str:
    if sys.platform == "win32":
        env_proc = os.environ.get("PROCESSOR_IDENTIFIER", "")
        try:
            proc = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except Exception:
            pass
        return env_proc or platform.processor() or "Unknown CPU"
    return platform.processor() or "Unknown CPU"


def _detect_nvidia_gpu() -> str | None:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return None
    try:
        proc = subprocess.run(
            [smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return "; ".join(line.strip() for line in proc.stdout.strip().splitlines())
    except Exception:
        return None
    return None


def _probe_openai_endpoint(api_base: str, timeout: float = 1.5) -> dict[str, Any] | None:
    url = f"{api_base.rstrip('/')}/models"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]
            spark_models = [m for m in models if "spark" in m.lower()]
            if not spark_models:
                return None
            return {"api_base": api_base, "spark_models": spark_models}
    except Exception:
        return None


def inspect_environment(workspace_dir: Path) -> EnvironmentReport:
    """Inspect GPU/CPU/RAM, free disk space, HF/GGUF cache, and active local inference servers."""
    drive = workspace_dir.drive or str(workspace_dir.anchor) or "/"
    usage = shutil.disk_usage(workspace_dir)

    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    hf_hub = hf_home / "hub"
    cached_spark: list[str] = []
    if hf_hub.exists():
        for entry in sorted(hf_hub.iterdir()):
            if "spark-x2.6" in entry.name.lower() or "spark-x2_6" in entry.name.lower():
                cached_spark.append(entry.name)

    local_ggufs: list[str] = []
    models_dir = workspace_dir / "models"
    if models_dir.exists():
        for p in sorted(models_dir.rglob("*.gguf")):
            local_ggufs.append(f"{p.name} ({p.stat().st_size / (1024**3):.2f} GiB)")
    env_gguf = os.environ.get("SPARK_GGUF_PATH")
    if env_gguf and Path(env_gguf).exists():
        p = Path(env_gguf)
        local_ggufs.append(f"{p} ({p.stat().st_size / (1024**3):.2f} GiB)")

    active_servers: list[dict[str, Any]] = []
    for base in DEFAULT_LOCAL_ENDPOINTS:
        info = _probe_openai_endpoint(base)
        if info is not None:
            active_servers.append(info)

    nvidia_gpu = _detect_nvidia_gpu()
    ram_gib = _detect_ram_gib()
    if nvidia_gpu:
        recommended = (
            "NVIDIA GPU detected: use `llama-server` / `Ollama` (`Spark-X2.6-4B-Q4_K_M.gguf`, 3.30 GiB) "
            "or `vLLM` / `transformers` BF16 (`XHToken/Spark-X2.6-4B`, 7.67 GiB)."
        )
    else:
        recommended = (
            f"No discrete NVIDIA GPU detected ({ram_gib} GiB system RAM): strongly recommend quantized "
            f"`{SPARK_GGUF_REPO}` (`{SPARK_GGUF_Q4_FILENAME}`, 3.300 GiB / 3.543 GB) via `llama.cpp` "
            f"`llama-server` (b10828+) or `Ollama` (`ollama run SparkLLM/Spark-X2.6-4B`) for fast CPU inference."
        )

    catalog = {
        "transformers_bf16": {
            "repo_id": SPARK_HF_REPO,
            "revision_sha": SPARK_HF_REVISION,
            "total_bytes": SPARK_HF_TOTAL_BYTES,
            "size_gib": round(SPARK_HF_TOTAL_BYTES / (1024**3), 3),
            "size_gb_decimal": round(SPARK_HF_TOTAL_BYTES / (1000**3), 3),
            "format": "safetensors (5 shards, bfloat16,Spark2_5ForCausalLM)",
        },
        "gguf_q4_k_m": {
            "repo_id": SPARK_GGUF_REPO,
            "revision_sha": SPARK_GGUF_REVISION,
            "filename": SPARK_GGUF_Q4_FILENAME,
            "total_bytes": SPARK_GGUF_Q4_BYTES,
            "size_gib": round(SPARK_GGUF_Q4_BYTES / (1024**3), 3),
            "size_gb_decimal": round(SPARK_GGUF_Q4_BYTES / (1000**3), 3),
            "format": "GGUF Q4_K_M (llama.cpp b10828+ / Ollama / LM Studio)",
        },
        "gguf_q8_0": {
            "repo_id": SPARK_GGUF_REPO,
            "revision_sha": SPARK_GGUF_REVISION,
            "filename": SPARK_GGUF_Q8_FILENAME,
            "total_bytes": SPARK_GGUF_Q8_BYTES,
            "size_gib": round(SPARK_GGUF_Q8_BYTES / (1024**3), 3),
            "size_gb_decimal": round(SPARK_GGUF_Q8_BYTES / (1000**3), 3),
            "format": "GGUF Q8_0",
        },
    }

    return EnvironmentReport(
        os_platform=platform.platform(),
        python_version=platform.python_version(),
        cpu_model=_detect_cpu_model(),
        logical_cores=os.cpu_count() or 1,
        ram_total_gib=ram_gib,
        nvidia_gpu=nvidia_gpu,
        disk_drive=drive,
        disk_total_gib=round(usage.total / (1024**3), 2),
        disk_free_gib=round(usage.free / (1024**3), 2),
        hf_cache_dir=str(hf_hub),
        cached_spark_repos=cached_spark,
        local_gguf_files=local_ggufs,
        active_local_servers=active_servers,
        recommended_runtime=recommended,
        models_catalog=catalog,
    )


def confirm_weight_download(
    env_report: EnvironmentReport,
    repo_id: str,
    revision: str,
    size_bytes: int,
    auto_yes: bool = False,
) -> bool:
    """Enforce Issue #32 requirement: show hardware, free space, cache, and size before downloading."""
    gib = size_bytes / (1024**3)
    gb = size_bytes / (1000**3)
    print("\n" + "=" * 74)
    print("  WEIGHT DOWNLOAD CONFIRMATION GATE (HER Hack-Astron #8 Rule #2)")
    print("=" * 74)
    print(f"  Target Model     : {repo_id} @ {revision[:12]}")
    print(f"  Download Size    : {size_bytes:,} bytes ({gib:.3f} GiB / {gb:.3f} GB)")
    print(f"  Detected CPU/GPU : {env_report.cpu_model} | GPU: {env_report.nvidia_gpu or 'None (Integrated/CPU)'}")
    print(f"  System RAM       : {env_report.ram_total_gib:.2f} GiB")
    print(f"  Free Disk ({env_report.disk_drive})   : {env_report.disk_free_gib:.2f} GiB free of {env_report.disk_total_gib:.2f} GiB")
    print(f"  Cached Spark Hub : {env_report.cached_spark_repos or 'None found in HF cache'}")
    print("=" * 74)

    if env_report.disk_free_gib < gib + 2.0:
        print(f"ERROR: Insufficient free disk space ({env_report.disk_free_gib:.2f} GiB) for {gib:.2f} GiB weights.")
        return False

    if auto_yes:
        print("User passed explicit `--yes` flag -> proceeding with download.")
        return True

    if not sys.stdin.isatty():
        print(
            "Non-interactive shell detected without `--yes`. Refusing unconfirmed multi-GB download.\n"
            "Re-run interactively or pass `--yes` after reviewing the size above."
        )
        return False

    ans = input(f"Proceed with downloading {gib:.3f} GiB ({gb:.3f} GB) now? [y/N]: ").strip().lower()
    return ans in ("y", "yes")


class OpenAICompatSparkRunner:
    """Runs inference against a local OpenAI-compatible server (`llama-server`, `vLLM`, `SGLang`, `Ollama`)."""

    def __init__(
        self,
        api_base: str = "http://127.0.0.1:18080/v1",
        model_name: str = "spark2.6",
        model_revision: str = SPARK_GGUF_REVISION,
        quantization: str = "Q4_K_M",
        thinking_mode: str = "none",
        temperature: float = 0.1,
        max_tokens: int = 2048,
        timeout_sec: int = 600,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.model_name = model_name
        self.model_revision = model_revision
        self.quantization = quantization
        self.thinking_mode = thinking_mode
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_sec = timeout_sec

    def _verify_spark_endpoint(self) -> None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(f"{self.api_base}/models", headers={"Accept": "application/json"})
        try:
            with opener.open(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [str(m.get("id", "")) for m in data.get("data", []) if isinstance(m, dict)]
                if models and not is_spark_model_list(models):
                    raise ValueError(
                        f"Refusing to run: endpoint {self.api_base} serves non-Spark models ({models[:3]}...). "
                        "Point `--api-base` at your local Spark-X2.6-4B server (e.g. port 18080 or Ollama 11434)."
                    )
        except urllib.error.URLError:
            pass

    def generate(self, messages: list[dict[str, str]], sample: ReleaseSample, cr: ChangeradarResult) -> InferenceResult:
        self._verify_spark_endpoint()
        chat_kwargs: dict[str, Any]
        if self.thinking_mode == "none":
            chat_kwargs = {"enable_thinking": False}
        else:
            chat_kwargs = {"enable_thinking": True, "reasoning_effort": self.thinking_mode}

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": 0.95,
            "max_tokens": self.max_tokens,
            "stream": True,
            "cache_prompt": False,
            "chat_template_kwargs": chat_kwargs,
        }

        body = json.dumps(payload).encode("utf-8")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer local-spark"},
            method="POST",
        )
        t0 = time.perf_counter()
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        served_model = self.model_name
        prompt_toks: int | None = None
        comp_toks = 0

        try:
            with opener.open(req, timeout=600) as resp:
                ctype = resp.headers.get("Content-Type", "")
                if "text/event-stream" in ctype:
                    for raw_line in resp:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        chunk = json.loads(data_str)
                        if chunk.get("model"):
                            served_model = chunk["model"]
                        if chunk.get("usage"):
                            prompt_toks = chunk["usage"].get("prompt_tokens", prompt_toks)
                            comp_toks = chunk["usage"].get("completion_tokens", comp_toks)
                        choices = chunk.get("choices") or []
                        if choices:
                            delta = choices[0].get("delta") or {}
                            c_piece = delta.get("content") or ""
                            r_piece = delta.get("reasoning_content") or delta.get("reasoning") or ""
                            if c_piece:
                                content_parts.append(c_piece)
                                comp_toks += 1
                                if comp_toks % 25 == 0:
                                    print(f"    [Spark stream] {comp_toks} tokens ({time.perf_counter() - t0:.1f}s)...", flush=True)
                            if r_piece:
                                reasoning_parts.append(r_piece)
                else:
                    resp_json = json.loads(resp.read().decode("utf-8"))
                    served_model = resp_json.get("model") or self.model_name
                    choice = (resp_json.get("choices") or [{}])[0]
                    msg = choice.get("message") or {}
                    content_parts.append(msg.get("content") or "")
                    reasoning_parts.append(msg.get("reasoning_content") or msg.get("reasoning") or "")
                    usage = resp_json.get("usage") or {}
                    prompt_toks = usage.get("prompt_tokens")
                    comp_toks = usage.get("completion_tokens") or 0
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Could not reach local Spark server at {self.api_base}/chat/completions ({exc}). "
                "Start llama-server / Ollama / vLLM first, or use `--backend transformers`."
            ) from exc
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        content = "".join(content_parts)
        reasoning = "".join(reasoning_parts)
        if reasoning and "<think>" not in content:
            raw_text = f"<think>\n{reasoning.strip()}\n</think>\n{content}"
        else:
            raw_text = content

        return InferenceResult(
            backend=f"openai_compat ({self.api_base})",
            is_dry_run=False,
            model_id=served_model,
            model_revision=self.model_revision,
            quantization_or_dtype=self.quantization,
            thinking_mode=self.thinking_mode,
            raw_text=raw_text,
            latency_ms=elapsed_ms,
            prompt_tokens=prompt_toks,
            completion_tokens=comp_toks or None,
            inference_settings={
                "api_base": self.api_base,
                "temperature": self.temperature,
                "top_p": 0.95,
                "max_tokens": self.max_tokens,
                "stream": True,
                "chat_template_kwargs": chat_kwargs,
            },
        )


class TransformersSparkRunner:
    """Runs local `XHToken/Spark-X2.6-4B` directly via Hugging Face `transformers`."""

    def __init__(
        self,
        model_id_or_path: str = SPARK_HF_REPO,
        revision: str = SPARK_HF_REVISION,
        thinking_mode: str = "none",
        temperature: float = 0.1,
        max_new_tokens: int = 2048,
        local_files_only: bool = False,
    ) -> None:
        try:
            import torch  # type: ignore
            from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Hugging Face `transformers` and `torch` are required for `--backend transformers`.\n"
                "Install with: pip install transformers==4.57.1 torch accelerate"
            ) from exc

        self._torch = torch
        self.model_id = model_id_or_path
        self.revision = revision
        self.thinking_mode = thinking_mode
        self.temperature = temperature
        self.max_new_tokens = max_new_tokens

        load_kwargs: dict[str, Any] = {
            "trust_remote_code": True,
            "local_files_only": local_files_only,
        }
        if Path(model_id_or_path).exists():
            rev_kw: dict[str, Any] = {}
        else:
            rev_kw = {"revision": revision}

        self.tokenizer = AutoTokenizer.from_pretrained(model_id_or_path, **rev_kw, **load_kwargs)
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(
            model_id_or_path,
            torch_dtype=dtype,
            device_map="auto" if torch.cuda.is_available() else None,
            **rev_kw,
            **load_kwargs,
        )
        self.dtype_str = str(dtype).replace("torch.", "")

    def generate(self, messages: list[dict[str, str]], sample: ReleaseSample, cr: ChangeradarResult) -> InferenceResult:
        enable_thinking = self.thinking_mode != "none"
        inputs = self.tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            enable_thinking=enable_thinking,
            return_dict=True,
            return_tensors="pt",
        )
        device = next(self.model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}
        prompt_len = int(inputs["input_ids"].shape[-1])

        gen_kwargs: dict[str, Any] = {
            "max_new_tokens": self.max_new_tokens,
        }
        if self.temperature > 0:
            gen_kwargs.update({"do_sample": True, "temperature": self.temperature, "top_p": 0.95, "top_k": 0})
        else:
            gen_kwargs.update({"do_sample": False})

        t0 = time.perf_counter()
        with self._torch.no_grad():
            outputs = self.model.generate(**inputs, **gen_kwargs)
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        gen_ids = outputs[0][prompt_len:]
        raw_text = self.tokenizer.decode(gen_ids, skip_special_tokens=True)
        return InferenceResult(
            backend="transformers_local",
            is_dry_run=False,
            model_id=self.model_id,
            model_revision=self.revision,
            quantization_or_dtype=self.dtype_str,
            thinking_mode=self.thinking_mode,
            raw_text=raw_text,
            latency_ms=elapsed_ms,
            prompt_tokens=prompt_len,
            completion_tokens=int(gen_ids.shape[-1]),
            inference_settings={
                "enable_thinking": enable_thinking,
                "temperature": self.temperature,
                "max_new_tokens": self.max_new_tokens,
            },
        )


class DryRunPreviewRunner:
    """Explicitly watermarked non-LLM dry-run builder for offline pipeline & test verification.

    NEVER claims to be Spark-X2.6-4B output: stamps `is_dry_run=True` and
    `backend='DRY_RUN_SYNTHETIC_PREVIEW'` on every record.
    """

    def generate(self, messages: list[dict[str, str]], sample: ReleaseSample, cr: ChangeradarResult) -> InferenceResult:
        t0 = time.perf_counter()
        # Map changed file -> seed symbol and seed -> callers/tests deterministically from changeradar JSON
        diff_changes = cr.diffparse.get("data", {}).get("changes", [])
        impact_entries = cr.propagate.get("data", {}).get("impact", [])
        selected_tests = cr.selected_tests

        seed_entries: list[tuple[str, str]] = []
        for ch in diff_changes:
            f = ch.get("file")
            for fn in ch.get("functions", []):
                if f and fn.get("node_id"):
                    seed_entries.append((f, fn["node_id"]))

        items_out: list[dict[str, Any]] = []
        for idx, rn in enumerate(sample.release_lines):
            txt = rn.text
            txt_lower = txt.lower()
            is_breaking = txt_lower.startswith("breaking") or "removed the deprecated" in txt_lower
            if is_breaking:
                sev = "breaking"
            elif "behavior change" in txt_lower:
                sev = "behavior_change"
            elif "deprecated" in txt_lower:
                sev = "deprecation"
            else:
                sev = "additive"

            uncertainty: str | None = None
            if "no owner" in txt_lower or "no target release date" in txt_lower or "future discussion" in txt_lower:
                uncertainty = "Deferred to future discussion; source states no owner or target release date is set."

            # Match release note line to seed symbol if its function/class name appears in the release note
            matched_file: str | None = None
            matched_seed: str | None = None
            for f_path, seed_id in seed_entries:
                short_sym = seed_id.split("::")[-1]
                parent_sym = seed_id.split("::")[-2] if seed_id.count("::") >= 2 else ""
                if short_sym in txt or (parent_sym and parent_sym in txt):
                    matched_file = f_path
                    matched_seed = seed_id
                    break

            affected_feats: list[str] = []
            rec_tests: list[str] = []
            if matched_seed:
                for imp in impact_entries:
                    if int(imp.get("distance", 0)) >= 1 and matched_seed in (imp.get("path") or []):
                        affected_feats.append(imp["node_id"])
                covered_set = {matched_seed, *affected_feats}
                for tst in selected_tests:
                    if set(tst.get("covers") or []) & covered_set:
                        rec_tests.append(tst["test_name"])

            code_spans = [m.strip("`") for m in extract_inline_tokens(txt)]
            items_out.append(
                {
                    "id": f"CHK-{idx + 1}",
                    "title": f"[DRY-RUN PREVIEW] {txt[:72].rstrip('.')}...",
                    "action": (
                        f"Update callers affecting {', '.join(affected_feats)} and run {', '.join(rec_tests)}."
                        if affected_feats
                        else "No code migration required; verify informational/compatibility note."
                    ),
                    "breaking": is_breaking,
                    "severity": sev,
                    "release_note_line_id": rn.line_id,
                    "verbatim_quote": txt,
                    "version_or_flag_tokens": code_spans[:4],
                    "uncertainty_note": uncertainty,
                    "traced_change": {
                        "changed_file": matched_file,
                        "changed_symbol": matched_seed,
                        "affected_features": affected_feats,
                        "recommended_tests": rec_tests,
                    },
                }
            )

        payload = {
            "step0": {
                "schema_version": "1.0",
                "mode": "diff",
                "target": {
                    "path": sample.repo_dir.as_posix(),
                    "tests_dir": (sample.repo_dir / "tests").as_posix(),
                },
                "scope": {"diff_file": "patch.diff"},
                "confidence": "high",
                "clarification_needed": [],
            },
            "items": items_out,
        }
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return InferenceResult(
            backend="DRY_RUN_SYNTHETIC_PREVIEW (NO SPARK WEIGHTS EXECUTED)",
            is_dry_run=True,
            model_id="DRY_RUN_NO_MODEL",
            model_revision="dry-run-preview-only",
            quantization_or_dtype="n/a",
            thinking_mode="none",
            raw_text=json.dumps(payload, indent=2, ensure_ascii=False),
            latency_ms=elapsed_ms,
            prompt_tokens=None,
            completion_tokens=None,
            inference_settings={"dry_run": True},
        )


def extract_inline_tokens(text: str) -> list[str]:
    import re as _re

    return [m.group(1) for m in _re.finditer(r"`([^`]+)`", text)]
