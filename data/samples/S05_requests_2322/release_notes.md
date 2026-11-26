# Requests v2.32.2 & urllib3 2.2.2 Security Release Notes (Curated Public Excerpt)
Source: https://github.com/psf/requests/releases/tag/v2.32.2

- Breaking Security Fix (`CVE-2024-35195`): Custom `TLSAdapter.get_connection_with_tls_context()` implementations in `v2.32.2` must include per-request `verify` in the connection pool key instead of reusing the first cached pool unconditionally.
- Breaking Security Fix (`CVE-2024-37891`): `strip_sensitive_redirect_headers()` now strips `Proxy-Authorization` automatically across cross-host redirects unless `trust_env_redirects=True` is explicitly set.
- Kept `idna>=2.5,<4` and `certifi>=2017.4.17` dependency bounds unchanged for Python `3.10+` installs.
- Updated `Session.mount("https://", adapter)` docstrings to document connection-pool thread safety.
