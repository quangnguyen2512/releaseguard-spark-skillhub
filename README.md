# 🛡️ ReleaseGuard — Verifiable Upgrade Checklist & AST Breaking-Change Tracer

**HER Hack-Astron #8 | Spark × SkillHub Agent Skills Challenge (`Developer Tools` Track)**

ReleaseGuard turns public open-source release notes and unified `git diff` patches into a **source-quoted developer upgrade checklist**, traces code-backed breaking changes through **SkillHub `global/changeradar`**'s deterministic AST call graph to affected downstream features and regression tests, and audits local **`Spark-X2.6-4B`** output through **7 deterministic citation & anti-hallucination gates** before explicit human sign-off.

## Why ReleaseGuard Stands Out
1. **True AST Feature Tracing (`global/changeradar` `v20260809.064909`):** Goes beyond line-level text checklists—executes `changeradar`'s 6-script stdlib AST engine (`cache.py → callgraph.py → diffparse.py → propagate.py → testselect.py`) to trace `git diff` hunks → changed seed functions → downstream feature callers → high-risk regression tests (compressing test runs by `33.3%` while keeping `100%` impact coverage).
2. **Strict Separation of Powers:** Enforces `changeradar/SKILL.md` Iron Laws #1–#3—local `Spark-X2.6-4B` synthesizes the developer checklist and classifies breaking polarity, while `verifier.py` blocks any invented version numbers, cross-line quotes, hallucinated call-graph nodes, unselected tests, or fabricated owners/dates.
3. **Explicit Human-in-the-Loop Gate:** Every checklist item initializes as `pending` (`Approved: 0 of N`) in the 4-panel interactive HTML walkthrough (`outputs/walkthrough_report.html`). Nothing is approved automatically.

## Quickstart

```powershell
# 1. Run all deterministic unit & integration tests (0 GPU / 0 network needed)
uv run pytest tests/test_releaseguard.py -v

# 2. Check hardware, free disk space, cache & exact Spark-X2.6-4B download sizes
python run_challenge.py --check-env

# 3. Verify full pipeline end-to-end in watermarked dry-run preview mode
python run_challenge.py --dry-run

# 4. Run real local Spark-X2.6-4B inference (llama.cpp / Ollama / vLLM or HF transformers)
python run_challenge.py --download-and-run --backend openai-compat --api-base http://127.0.0.1:18080/v1 --thinking none
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for system invariants and [SUBMIT_GUIDE.md](SUBMIT_GUIDE.md) for 1-command local inference and submission instructions.
