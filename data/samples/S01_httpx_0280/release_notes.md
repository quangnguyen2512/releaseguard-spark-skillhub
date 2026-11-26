# httpx 0.28.0 Release Notes (Curated Public Excerpt)
Source: https://github.com/encode/httpx/releases/tag/0.28.0

- Breaking: Removed the deprecated `proxies=...` parameter from `ClientSession.open_connection()` in `0.28.0`; migrate callers to `proxy=...` for single-URL proxy routing.
- Deprecated boolean/string `verify` shortcuts in `build_ssl_settings(verify=..., cert=...)` in favor of explicit `ssl.SSLContext` instances in `0.28.0`.
- Preserved default connection pool limits (`max_keepalive_connections=20`, `max_connections=100`) unchanged for synchronous HTTP transports.
- Fixed hexadecimal `nonce_count` formatting in `DigestAuth` retry challenges without changing public constructor arguments.
