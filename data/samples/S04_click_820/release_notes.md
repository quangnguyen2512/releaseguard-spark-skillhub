# Click 8.2.0 Release Notes (Curated Public Excerpt)
Source: https://github.com/pallets/click/releases/tag/8.2.0

- Breaking: Removed the deprecated `mix_stderr` parameter from `CliRunner.__init__()` in `8.2.0`; read `result.stdout` and `result.stderr` separately.
- Behavior change: `resolve_envvar_value()` now treats an empty environment variable (`""`) as `None` (unset) instead of returning `""`.
- Added Fish `3.7+` completion script templates without changing Bash or Zsh completion output.
- Kept `Context.protected_args` deprecated and scheduled for removal in Click `9.0`.
