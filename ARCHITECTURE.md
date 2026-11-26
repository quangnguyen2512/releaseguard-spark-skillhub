# ARCHITECTURE — ReleaseGuard (Spark-X2.6-4B × SkillHub Challenge)

Verifiable Upgrade Checklist & Breaking-Change Tracer built for **HER Hack-Astron #8 | Spark × SkillHub Agent Skills Challenge** (`XHToken/Spark-X2.6#32`, **Developer Tools** track).

## Core Invariants
1. **Hardware-First & Explicit User Consent:** Always inspects GPU/CPU/RAM, free disk space, and local Hugging Face / GGUF cache before any weight download (`--check-env`), displaying exact byte/GiB sizes and revision SHAs (`XHToken/Spark-X2.6-4B` @ `64ca8f2a...`, `7.673 GiB`; `XHToken/Spark-X2.6-4B-GGUF` `Q4_K_M` @ `9d716770...`, `3.300 GiB`) and requiring confirmation.
2. **Strict Separation of Powers (`changeradar` Red Lines #1–#3):** Deterministic Python + SkillHub `global/changeradar` (`v20260809.064909`) computes AST call graphs, diff-to-symbol seeds, blast-radius propagation, and regression test selection. Local `Spark-X2.6-4B` performs structured understanding + source-grounded checklist synthesis, never inventing graph nodes or metrics.
3. **Zero Fabricated Inference & Explicit Human Sign-Off:** `--dry-run` outputs are watermarked `DRY_RUN_SYNTHETIC_PREVIEW` and blocked from populating final submission results. Every checklist item starts `pending` (`Approved: 0 of N`) until human review.

## Directory Boundaries
```text
spark_x26_skillhub_100usd/
├── ARCHITECTURE.md                      # System map, DAG & invariants (<120 lines)
├── README.md                            # Quickstart, architecture & benchmark overview
├── requirements.txt                     # Minimal runtime + optional transformers/pytest deps
├── run_challenge.py                     # CLI: --check-env | --dry-run | --download-and-run
├── HF_DISCUSSION_TEMPLATE_READY.md      # Official Issue #32 HF Discussion template (auto-fillable)
├── SUBMIT_GUIDE.md                      # Step-by-step local inference, screenshot & submit guide
├── .agents/skills/changeradar/          # Installed SkillHub skill v20260809.064909 + metadata.json
├── data/samples/                        # 5 curated public OSS release samples + ground truth
│   ├── S01_httpx_0280/                  # encode/httpx 0.28.0 (proxies removal & SSLContext)
│   ├── S02_fastapi_01150/               # fastapi/fastapi 0.115.0 (Query regex->pattern & lifespan)
│   ├── S03_pydantic_2100/               # pydantic/pydantic v2.10.0 (allow_mutation error & ISO tz)
│   ├── S04_click_820/                   # pallets/click 8.2.0 (CliRunner mix_stderr & envvar="")
│   └── S05_requests_2322/               # psf/requests 2.32.2 + urllib3 2.2.2 (TLS verify & redirects)
├── src/releaseguard/
│   ├── models.py                        # Dataclasses & JSON schemas for pipeline & verification
│   ├── parser.py                        # Numbered release-note & unified git diff parser
│   ├── skill_bridge.py                  # SkillHub changeradar SHA-256 verifier & 5-script runner
│   ├── prompts.py                       # Skill-guided Step 0 + Upgrade Checklist prompt builder
│   ├── spark_runner.py                  # Env checker + OpenAI-compat (llama.cpp/vllm/ollama) & HF runners
│   ├── verifier.py                      # 7-Gate Deterministic Ground-Truth Citation & Hallucination Verifier
│   ├── html_report.py                   # Self-contained 4-panel interactive HTML Visual Walkthrough
│   └── template_filler.py               # Populates HF Discussion template from verified real Spark logs
├── outputs/                             # Generated traces, HTML walkthrough & filled HF template
└── tests/
    └── test_releaseguard.py             # Pytest suite (parser, skill bridge, prompts, 7 gates, HTML, CLI)
```

## Execution DAG
```text
data/samples/S01..S05 (release_notes.md + patch.diff + repo/ + ground_truth.json)
   │
   ├──► parser.py ───────────────────────────────┐
   │                                             ▼
   ├──► skill_bridge.py (.agents/skills/changeradar: cache -> callgraph -> diffparse -> propagate -> testselect)
   │                                             │
   ▼                                             ▼
prompts.py (Step 0 Contract + Source-Grounded Checklist Prompt)
   │
   ▼
spark_runner.py (Local Spark-X2.6-4B via llama.cpp/vLLM/Ollama OR HF Transformers)
   │
   ▼
verifier.py (7 Hard Gates: Schema, Verbatim Quote, Version/Flag, Diff Symbol, Call-Graph Red-Line, Polarity, Gold Score)
   │
   ├──► outputs/runs/<mode>/<sample>/trace.json + outputs/walkthrough_report.html (Explicit HITL Sign-Off)
   └──► template_filler.py ──► outputs/HF_DISCUSSION_FILLED.md (Real Spark-X2.6-4B runs only)
```

## External Integrations & Provenance
- **SkillHub Package:** `global/changeradar` (`v20260809.064909`, `versionId: 25785`, `sha256:4fb641ead1b8fe8b43d57a83c828627fbfb152396d9cf9952aa9851619d27a4a`, registry `https://skill.xfyun.cn`)
- **Local Model Checkpoints:** `XHToken/Spark-X2.6-4B` (`64ca8f2a295b8ceb2757b9d4749a6558c4759e5b`) & `XHToken/Spark-X2.6-4B-GGUF` (`9d716770ac7477776de5f891f70cdf98b003a5cd`)
