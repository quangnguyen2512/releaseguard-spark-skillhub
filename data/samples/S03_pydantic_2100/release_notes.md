# Pydantic v2.10.0 Release Notes (Curated Public Excerpt)
Source: https://github.com/pydantic/pydantic/releases/tag/v2.10.0

- Breaking: Passing `allow_mutation` inside `compile_model_config()` in `v2.10.0` now raises `ValueError("allow_mutation is removed; use frozen=True")` instead of a deprecation warning.
- Behavior change: `dump_audit_record()` now preserves explicit UTC/offset suffixes on timezone-aware ISO-8601 timestamps rather than stripping `+00:00`.
- Added opt-in `experimental_allow_partial="trailing-strings"` streaming flag (disabled by default; no impact on standard validation).
- Accelerated union schema compilation by `18%` with byte-identical JSON Schema output.
