# FastAPI 0.115.0 Release Notes (Curated Public Excerpt)
Source: https://github.com/fastapi/fastapi/releases/tag/0.115.0

- Breaking: Removed the deprecated `regex` parameter in `build_query_validator()` under Pydantic v2; migrate all query validators to `pattern` before upgrading to `0.115.0`.
- Deprecated `on_event("startup")` hook registration in `register_lifespan_hooks()`; pass an async `lifespan` context manager instead.
- Added `Annotated` form model binding support without altering existing field-by-field `Form(...)` signatures.
- Future note: `OAuth2PasswordBearer` `tokenUrl` relative-path rules will be revisited in a future discussion; no owner or target release date is set.
