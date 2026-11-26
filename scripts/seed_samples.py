# -*- coding: utf-8 -*-
"""Deterministic generator for the 5 curated public OSS release samples in data/samples/.

Generates exact unified git diffs (`patch.diff`) between `before_files` and `after_files`,
writes the post-upgrade `repo/` snapshot + `tests/`, verbatim `release_notes.md`,
and pre-committed `ground_truth.json` acceptance criteria.
"""
from __future__ import annotations

import difflib
import json
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "data" / "samples"


def make_git_diff(before_files: dict[str, str], after_files: dict[str, str]) -> str:
    chunks: list[str] = []
    for rel in sorted(after_files.keys()):
        if rel not in before_files:
            continue
        old_src = before_files[rel]
        new_src = after_files[rel]
        if old_src == new_src:
            continue
        diff_lines = list(
            difflib.unified_diff(
                old_src.splitlines(keepends=True),
                new_src.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
                n=3,
            )
        )
        if diff_lines:
            chunks.append(f"diff --git a/{rel} b/{rel}\nindex 1111111..2222222 100644\n" + "".join(diff_lines))
    return "".join(chunks)


SAMPLES = [
    {
        "id": "S01_httpx_0280",
        "project": "encode/httpx",
        "from_version": "0.27.2",
        "to_version": "0.28.0",
        "release_url": "https://github.com/encode/httpx/releases/tag/0.28.0",
        "license": "BSD-3-Clause",
        "release_notes": """# httpx 0.28.0 Release Notes (Curated Public Excerpt)
Source: https://github.com/encode/httpx/releases/tag/0.28.0

- Breaking: Removed the deprecated `proxies=...` parameter from `ClientSession.open_connection()` in `0.28.0`; migrate callers to `proxy=...` for single-URL proxy routing.
- Deprecated boolean/string `verify` shortcuts in `build_ssl_settings(verify=..., cert=...)` in favor of explicit `ssl.SSLContext` instances in `0.28.0`.
- Preserved default connection pool limits (`max_keepalive_connections=20`, `max_connections=100`) unchanged for synchronous HTTP transports.
- Fixed hexadecimal `nonce_count` formatting in `DigestAuth` retry challenges without changing public constructor arguments.
""",
        "before_files": {
            "http_client/config.py": """import ssl


def build_ssl_settings(verify=True, cert=None):
    ctx = ssl.create_default_context()
    if cert is not None:
        ctx.load_cert_chain(cert)
    return ctx
""",
            "http_client/transport.py": """from http_client.config import build_ssl_settings


class ClientSession:
    def __init__(self, timeout=10.0):
        self.timeout = timeout

    def open_connection(self, url, proxies=None, ssl_context=None):
        ctx = build_ssl_settings(verify=ssl_context)
        return {"url": url, "proxies": proxies, "ssl_ready": ctx is not None, "timeout": self.timeout}
""",
        },
        "after_files": {
            "http_client/__init__.py": "",
            "http_client/config.py": """import ssl


def build_ssl_settings(verify=True, cert=None):
    if isinstance(verify, ssl.SSLContext):
        return verify
    ctx = ssl.create_default_context()
    if cert is not None:
        ctx.load_cert_chain(cert)
    return ctx
""",
            "http_client/transport.py": """from http_client.config import build_ssl_settings


class ClientSession:
    def __init__(self, timeout=10.0):
        self.timeout = timeout

    def open_connection(self, url, proxy=None, ssl_context=None):
        ctx = build_ssl_settings(verify=ssl_context)
        return {"url": url, "proxy": proxy, "ssl_ready": ctx is not None, "timeout": self.timeout}
""",
            "services/__init__.py": "",
            "services/webhook_sender.py": """from http_client.transport import ClientSession


class WebhookDispatcher:
    def __init__(self):
        self.session = ClientSession(timeout=5.0)

    def deliver_event(self, endpoint_url, outbound_proxy=None):
        return self.session.open_connection(endpoint_url, proxy=outbound_proxy)
""",
            "services/oauth_fetcher.py": """from http_client.config import build_ssl_settings
from http_client.transport import ClientSession


def refresh_access_token(token_url, custom_ssl):
    ctx = build_ssl_settings(verify=custom_ssl)
    client = ClientSession(timeout=3.0)
    return client.open_connection(token_url, ssl_context=ctx)
""",
            "services/retry_backoff.py": """def compute_backoff_delay(attempt, base=0.5):
    return base * (2 ** attempt)
""",
            "tests/__init__.py": "",
            "tests/test_webhook_sender.py": """from services.webhook_sender import WebhookDispatcher


def test_deliver_event_uses_proxy():
    dispatcher = WebhookDispatcher()
    res = dispatcher.deliver_event("https://hooks.example.com", outbound_proxy="http://proxy.local:8080")
    assert res["proxy"] == "http://proxy.local:8080"
""",
            "tests/test_oauth_fetcher.py": """import ssl
from services.oauth_fetcher import refresh_access_token


def test_refresh_access_token_ssl_context():
    ctx = ssl.create_default_context()
    res = refresh_access_token("https://auth.example.com/token", ctx)
    assert res["ssl_ready"] is True
""",
            "tests/test_retry_backoff.py": """from services.retry_backoff import compute_backoff_delay


def test_compute_backoff_delay():
    assert compute_backoff_delay(2, base=0.5) == 2.0
""",
        },
        "ground_truth": {
            "acceptance_criteria": [
                "Must identify removal of proxies=... in favor of proxy=... as breaking=true with verbatim RN-1 quote.",
                "Must identify deprecation of non-SSLContext verify/cert inputs in build_ssl_settings() as breaking=false (deprecation) grounded in RN-2.",
                "Must NOT mark RN-3 (max_keepalive_connections=20, max_connections=100 unchanged) or RN-4 (DigestAuth bugfix) as breaking=true.",
                "Must trace changed symbols http_client/transport.py::ClientSession::open_connection and http_client/config.py::build_ssl_settings to downstream features WebhookDispatcher.deliver_event and refresh_access_token.",
                "Must select regression tests test_deliver_event_uses_proxy and test_refresh_access_token_ssl_context while excluding unrelated test_compute_backoff_delay.",
            ],
            "expected_breaking_line_ids": ["RN-1"],
            "non_breaking_trap_line_ids": ["RN-2", "RN-3", "RN-4"],
            "must_include_tokens": ["0.28.0", "proxies", "proxy", "SSLContext"],
            "expected_changed_files": ["http_client/config.py", "http_client/transport.py"],
            "expected_seed_nodes": [
                "http_client/config.py::build_ssl_settings",
                "http_client/transport.py::ClientSession::open_connection",
            ],
            "expected_affected_callers": [
                "services/webhook_sender.py::WebhookDispatcher::deliver_event",
                "services/oauth_fetcher.py::refresh_access_token",
            ],
            "expected_selected_tests": [
                "test_deliver_event_uses_proxy",
                "test_refresh_access_token_ssl_context",
            ],
            "excluded_unrelated_tests": ["test_compute_backoff_delay"],
        },
    },
    {
        "id": "S02_fastapi_01150",
        "project": "fastapi/fastapi",
        "from_version": "0.114.2",
        "to_version": "0.115.0",
        "release_url": "https://github.com/fastapi/fastapi/releases/tag/0.115.0",
        "license": "MIT",
        "release_notes": """# FastAPI 0.115.0 Release Notes (Curated Public Excerpt)
Source: https://github.com/fastapi/fastapi/releases/tag/0.115.0

- Breaking: Removed the deprecated `regex` parameter in `build_query_validator()` under Pydantic v2; migrate all query validators to `pattern` before upgrading to `0.115.0`.
- Deprecated `on_event("startup")` hook registration in `register_lifespan_hooks()`; pass an async `lifespan` context manager instead.
- Added `Annotated` form model binding support without altering existing field-by-field `Form(...)` signatures.
- Future note: `OAuth2PasswordBearer` `tokenUrl` relative-path rules will be revisited in a future discussion; no owner or target release date is set.
""",
        "before_files": {
            "api_core/params.py": """import re


def build_query_validator(regex=None, max_length=64):
    compiled = re.compile(regex) if regex else None
    return {"regex": regex, "compiled": compiled, "max_length": max_length}
""",
            "api_core/lifespan.py": """def register_lifespan_hooks(on_event=None, lifespan=None):
    if lifespan is None:
        return {"mode": on_event or "default", "active": False}
    return {"mode": "lifespan_ctx", "handler": lifespan, "active": True}
""",
        },
        "after_files": {
            "api_core/__init__.py": "",
            "api_core/params.py": """import re


def build_query_validator(pattern=None, max_length=64):
    compiled = re.compile(pattern) if pattern else None
    return {"pattern": pattern, "compiled": compiled, "max_length": max_length}
""",
            "api_core/lifespan.py": """def register_lifespan_hooks(lifespan=None):
    if lifespan is None:
        return {"mode": "default", "active": False}
    return {"mode": "lifespan_ctx", "handler": lifespan, "active": True}
""",
            "endpoints/__init__.py": "",
            "endpoints/search_api.py": """from api_core.params import build_query_validator


def search_items_endpoint(raw_sku):
    rule = build_query_validator(pattern=r"^[A-Z0-9_-]+$", max_length=32)
    matched = bool(rule["compiled"].match(raw_sku))
    return {"sku": raw_sku, "valid": matched}
""",
            "endpoints/app_factory.py": """from api_core.lifespan import register_lifespan_hooks


def create_service_app(lifespan_cm=None):
    hooks = register_lifespan_hooks(lifespan=lifespan_cm)
    return {"service": "catalog-api", "lifespan": hooks}
""",
            "endpoints/healthcheck.py": """def liveness_probe():
    return {"status": "ok"}
""",
            "tests/__init__.py": "",
            "tests/test_search_api.py": """from endpoints.search_api import search_items_endpoint


def test_search_items_pattern_validation():
    assert search_items_endpoint("SKU_100")["valid"] is True
""",
            "tests/test_app_factory.py": """from endpoints.app_factory import create_service_app


def test_create_service_app_lifespan():
    app = create_service_app(lifespan_cm="async_ctx")
    assert app["lifespan"]["mode"] == "lifespan_ctx"
""",
            "tests/test_healthcheck.py": """from endpoints.healthcheck import liveness_probe


def test_liveness_probe():
    assert liveness_probe()["status"] == "ok"
""",
        },
        "ground_truth": {
            "acceptance_criteria": [
                "Must flag removal of regex in build_query_validator() -> pattern as breaking=true grounded in RN-1.",
                "Must trace build_query_validator() to endpoints/search_api.py::search_items_endpoint and register_lifespan_hooks() to endpoints/app_factory.py::create_service_app.",
                "Must NOT mark RN-3 (Annotated Form additive support) as breaking=true.",
                "Must preserve uncertainty in RN-4 (no owner or release date invented for OAuth2PasswordBearer tokenUrl).",
            ],
            "expected_breaking_line_ids": ["RN-1"],
            "non_breaking_trap_line_ids": ["RN-2", "RN-3", "RN-4"],
            "must_include_tokens": ["0.115.0", "regex", "pattern", "lifespan"],
            "expected_changed_files": ["api_core/lifespan.py", "api_core/params.py"],
            "expected_seed_nodes": [
                "api_core/params.py::build_query_validator",
                "api_core/lifespan.py::register_lifespan_hooks",
            ],
            "expected_affected_callers": [
                "endpoints/search_api.py::search_items_endpoint",
                "endpoints/app_factory.py::create_service_app",
            ],
            "expected_selected_tests": [
                "test_search_items_pattern_validation",
                "test_create_service_app_lifespan",
            ],
            "excluded_unrelated_tests": ["test_liveness_probe"],
        },
    },
    {
        "id": "S03_pydantic_2100",
        "project": "pydantic/pydantic",
        "from_version": "2.9.2",
        "to_version": "2.10.0",
        "release_url": "https://github.com/pydantic/pydantic/releases/tag/v2.10.0",
        "license": "MIT",
        "release_notes": """# Pydantic v2.10.0 Release Notes (Curated Public Excerpt)
Source: https://github.com/pydantic/pydantic/releases/tag/v2.10.0

- Breaking: Passing `allow_mutation` inside `compile_model_config()` in `v2.10.0` now raises `ValueError("allow_mutation is removed; use frozen=True")` instead of a deprecation warning.
- Behavior change: `dump_audit_record()` now preserves explicit UTC/offset suffixes on timezone-aware ISO-8601 timestamps rather than stripping `+00:00`.
- Added opt-in `experimental_allow_partial="trailing-strings"` streaming flag (disabled by default; no impact on standard validation).
- Accelerated union schema compilation by `18%` with byte-identical JSON Schema output.
""",
        "before_files": {
            "validation/schema_config.py": """def compile_model_config(config_dict):
    if "allow_mutation" in config_dict:
        config_dict = {"frozen": not config_dict["allow_mutation"]}
    return {"frozen": bool(config_dict.get("frozen", False)), "extra": config_dict.get("extra", "ignore")}
""",
            "validation/serializer.py": """def dump_audit_record(event_name, iso_timestamp):
    return {"event": event_name, "recorded_at": iso_timestamp.replace("+00:00", "Z")}
""",
        },
        "after_files": {
            "validation/__init__.py": "",
            "validation/schema_config.py": """def compile_model_config(config_dict):
    if "allow_mutation" in config_dict:
        raise ValueError("allow_mutation is removed; use frozen=True")
    return {"frozen": bool(config_dict.get("frozen", False)), "extra": config_dict.get("extra", "ignore")}
""",
            "validation/serializer.py": """def dump_audit_record(event_name, iso_timestamp):
    return {"event": event_name, "recorded_at": iso_timestamp}
""",
            "billing/__init__.py": "",
            "billing/ledger_writer.py": """from validation.schema_config import compile_model_config


def append_immutable_entry(raw_cfg, amount_cents):
    cfg = compile_model_config(raw_cfg)
    return {"frozen": cfg["frozen"], "amount_cents": amount_cents}
""",
            "billing/invoice_exporter.py": """from validation.serializer import dump_audit_record


def export_invoice_json(invoice_id, created_iso):
    payload = dump_audit_record(f"invoice:{invoice_id}", created_iso)
    return payload
""",
            "billing/currency_math.py": """def cents_to_dollars(cents):
    return round(cents / 100.0, 2)
""",
            "tests/__init__.py": "",
            "tests/test_ledger_writer.py": """from billing.ledger_writer import append_immutable_entry


def test_append_immutable_entry_frozen():
    entry = append_immutable_entry({"frozen": True}, 2500)
    assert entry["frozen"] is True
""",
            "tests/test_invoice_exporter.py": """from billing.invoice_exporter import export_invoice_json


def test_export_invoice_json_preserves_tz():
    out = export_invoice_json("INV-9", "2026-11-20T08:00:00+00:00")
    assert out["recorded_at"].endswith("+00:00")
""",
            "tests/test_currency_math.py": """from billing.currency_math import cents_to_dollars


def test_cents_to_dollars():
    assert cents_to_dollars(1999) == 19.99
""",
        },
        "ground_truth": {
            "acceptance_criteria": [
                "Must mark allow_mutation removal in compile_model_config() (use frozen=True) as breaking=true grounded in RN-1.",
                "Must trace compile_model_config() to billing/ledger_writer.py::append_immutable_entry and dump_audit_record() to billing/invoice_exporter.py::export_invoice_json.",
                "Must NOT mark RN-3 (opt-in experimental_allow_partial disabled by default) or RN-4 (18% speed improvement) as breaking=true.",
                "Must preserve exact numbers (v2.10.0, +00:00, 18%) without inventing new metrics.",
            ],
            "expected_breaking_line_ids": ["RN-1"],
            "non_breaking_trap_line_ids": ["RN-2", "RN-3", "RN-4"],
            "must_include_tokens": ["v2.10.0", "allow_mutation", "frozen=True"],
            "expected_changed_files": ["validation/schema_config.py", "validation/serializer.py"],
            "expected_seed_nodes": [
                "validation/schema_config.py::compile_model_config",
                "validation/serializer.py::dump_audit_record",
            ],
            "expected_affected_callers": [
                "billing/ledger_writer.py::append_immutable_entry",
                "billing/invoice_exporter.py::export_invoice_json",
            ],
            "expected_selected_tests": [
                "test_append_immutable_entry_frozen",
                "test_export_invoice_json_preserves_tz",
            ],
            "excluded_unrelated_tests": ["test_cents_to_dollars"],
        },
    },
    {
        "id": "S04_click_820",
        "project": "pallets/click",
        "from_version": "8.1.7",
        "to_version": "8.2.0",
        "release_url": "https://github.com/pallets/click/releases/tag/8.2.0",
        "license": "BSD-3-Clause",
        "release_notes": """# Click 8.2.0 Release Notes (Curated Public Excerpt)
Source: https://github.com/pallets/click/releases/tag/8.2.0

- Breaking: Removed the deprecated `mix_stderr` parameter from `CliRunner.__init__()` in `8.2.0`; read `result.stdout` and `result.stderr` separately.
- Behavior change: `resolve_envvar_value()` now treats an empty environment variable (`""`) as `None` (unset) instead of returning `""`.
- Added Fish `3.7+` completion script templates without changing Bash or Zsh completion output.
- Kept `Context.protected_args` deprecated and scheduled for removal in Click `9.0`.
""",
        "before_files": {
            "cli_kit/testing_harness.py": """class CliRunner:
    def __init__(self, charset="utf-8", env=None, mix_stderr=True):
        self.charset = charset
        self.env = env or {}
        self.mix_stderr = mix_stderr

    def run_command(self, cmd_name):
        return {"cmd": cmd_name, "stdout": "ok", "stderr": ""}
""",
            "cli_kit/options.py": """def resolve_envvar_value(env_map, key):
    raw = env_map.get(key)
    if raw is None:
        return None
    return raw
""",
        },
        "after_files": {
            "cli_kit/__init__.py": "",
            "cli_kit/testing_harness.py": """class CliRunner:
    def __init__(self, charset="utf-8", env=None):
        self.charset = charset
        self.env = env or {}

    def run_command(self, cmd_name):
        return {"cmd": cmd_name, "stdout": "ok", "stderr": ""}
""",
            "cli_kit/options.py": """def resolve_envvar_value(env_map, key):
    raw = env_map.get(key)
    if raw is None or raw == "":
        return None
    return raw
""",
            "runners/__init__.py": "",
            "runners/deploy_harness.py": """from cli_kit.testing_harness import CliRunner


def invoke_deploy_cli(target_env):
    runner = CliRunner(charset="utf-8", env={"DEPLOY_ENV": target_env})
    return runner.run_command("deploy")
""",
            "runners/env_loader.py": """from cli_kit.options import resolve_envvar_value


def load_runtime_flags(environ):
    region = resolve_envvar_value(environ, "CLOUD_REGION")
    return {"region": region or "us-east-1"}
""",
            "runners/ansi_colors.py": """def strip_ansi(text):
    return text.replace("\\x1b[0m", "")
""",
            "tests/__init__.py": "",
            "tests/test_deploy_harness.py": """from runners.deploy_harness import invoke_deploy_cli


def test_invoke_deploy_cli_runner():
    res = invoke_deploy_cli("staging")
    assert res["stdout"] == "ok"
""",
            "tests/test_env_loader.py": """from runners.env_loader import load_runtime_flags


def test_load_runtime_flags_empty_envvar():
    cfg = load_runtime_flags({"CLOUD_REGION": ""})
    assert cfg["region"] == "us-east-1"
""",
            "tests/test_ansi_colors.py": """from runners.ansi_colors import strip_ansi


def test_strip_ansi():
    assert strip_ansi("hi\\x1b[0m") == "hi"
""",
        },
        "ground_truth": {
            "acceptance_criteria": [
                "Must mark removal of mix_stderr from CliRunner.__init__() in 8.2.0 as breaking=true grounded in RN-1.",
                "Must trace CliRunner.__init__ and resolve_envvar_value to runners/deploy_harness.py::invoke_deploy_cli and runners/env_loader.py::load_runtime_flags.",
                "Must NOT mark RN-3 (Fish 3.7+ completions) or RN-4 (Context.protected_args scheduled for 9.0, not yet removed) as breaking=true in 8.2.0.",
            ],
            "expected_breaking_line_ids": ["RN-1"],
            "non_breaking_trap_line_ids": ["RN-2", "RN-3", "RN-4"],
            "must_include_tokens": ["8.2.0", "mix_stderr", "resolve_envvar_value"],
            "expected_changed_files": ["cli_kit/options.py", "cli_kit/testing_harness.py"],
            "expected_seed_nodes": [
                "cli_kit/options.py::resolve_envvar_value",
                "cli_kit/testing_harness.py::CliRunner::__init__",
            ],
            "expected_affected_callers": [
                "runners/deploy_harness.py::invoke_deploy_cli",
                "runners/env_loader.py::load_runtime_flags",
            ],
            "expected_selected_tests": [
                "test_invoke_deploy_cli_runner",
                "test_load_runtime_flags_empty_envvar",
            ],
            "excluded_unrelated_tests": ["test_strip_ansi"],
        },
    },
    {
        "id": "S05_requests_2322",
        "project": "psf/requests + urllib3",
        "from_version": "2.31.0",
        "to_version": "2.32.2",
        "release_url": "https://github.com/psf/requests/releases/tag/v2.32.2",
        "license": "Apache-2.0",
        "release_notes": """# Requests v2.32.2 & urllib3 2.2.2 Security Release Notes (Curated Public Excerpt)
Source: https://github.com/psf/requests/releases/tag/v2.32.2

- Breaking Security Fix (`CVE-2024-35195`): Custom `TLSAdapter.get_connection_with_tls_context()` implementations in `v2.32.2` must include per-request `verify` in the connection pool key instead of reusing the first cached pool unconditionally.
- Breaking Security Fix (`CVE-2024-37891`): `strip_sensitive_redirect_headers()` now strips `Proxy-Authorization` automatically across cross-host redirects unless `trust_env_redirects=True` is explicitly set.
- Kept `idna>=2.5,<4` and `certifi>=2017.4.17` dependency bounds unchanged for Python `3.10+` installs.
- Updated `Session.mount("https://", adapter)` docstrings to document connection-pool thread safety.
""",
        "before_files": {
            "net_transport/adapters.py": """class TLSAdapter:
    def __init__(self):
        self._pools = {}

    def get_connection_with_tls_context(self, host, verify=True):
        pool_key = host
        if pool_key not in self._pools:
            self._pools[pool_key] = {"host": host, "verify": bool(verify)}
        return self._pools[pool_key]
""",
            "net_transport/redirects.py": """def strip_sensitive_redirect_headers(headers, same_origin):
    cleaned = dict(headers)
    if not same_origin:
        cleaned.pop("Authorization", None)
    return cleaned
""",
        },
        "after_files": {
            "net_transport/__init__.py": "",
            "net_transport/adapters.py": """class TLSAdapter:
    def __init__(self):
        self._pools = {}

    def get_connection_with_tls_context(self, host, verify=True):
        pool_key = (host, bool(verify))
        if pool_key not in self._pools:
            self._pools[pool_key] = {"host": host, "verify": bool(verify)}
        return self._pools[pool_key]
""",
            "net_transport/redirects.py": """def strip_sensitive_redirect_headers(headers, same_origin, trust_env_redirects=False):
    cleaned = dict(headers)
    if not same_origin and not trust_env_redirects:
        cleaned.pop("Proxy-Authorization", None)
        cleaned.pop("Authorization", None)
    return cleaned
""",
            "clients/__init__.py": "",
            "clients/artifact_fetcher.py": """from net_transport.adapters import TLSAdapter


def download_release_tarball(host, strict_tls=True):
    adapter = TLSAdapter()
    return adapter.get_connection_with_tls_context(host, verify=strict_tls)
""",
            "clients/mirror_sync.py": """from net_transport.redirects import strip_sensitive_redirect_headers


def follow_mirror_redirect(req_headers, is_same_host):
    return strip_sensitive_redirect_headers(req_headers, same_origin=is_same_host)
""",
            "clients/cookie_jar.py": """def parse_cookie_pair(header_val):
    k, _, v = header_val.partition("=")
    return {k.strip(): v.strip()}
""",
            "tests/__init__.py": "",
            "tests/test_artifact_fetcher.py": """from clients.artifact_fetcher import download_release_tarball


def test_download_release_tarball_verify_key():
    conn = download_release_tarball("files.example.org", strict_tls=False)
    assert conn["verify"] is False
""",
            "tests/test_mirror_sync.py": """from clients.mirror_sync import follow_mirror_redirect


def test_follow_mirror_redirect_strips_proxy_auth():
    out = follow_mirror_redirect({"Proxy-Authorization": "Basic abc", "Accept": "*/*"}, is_same_host=False)
    assert "Proxy-Authorization" not in out
""",
            "tests/test_cookie_jar.py": """from clients.cookie_jar import parse_cookie_pair


def test_parse_cookie_pair():
    assert parse_cookie_pair("sid=42") == {"sid": "42"}
""",
        },
        "ground_truth": {
            "acceptance_criteria": [
                "Must mark CVE-2024-35195 (verify pool key in get_connection_with_tls_context) and CVE-2024-37891 (Proxy-Authorization stripping across redirects) as breaking=true security changes grounded in RN-1 and RN-2.",
                "Must trace TLSAdapter.get_connection_with_tls_context to clients/artifact_fetcher.py::download_release_tarball and strip_sensitive_redirect_headers to clients/mirror_sync.py::follow_mirror_redirect.",
                "Must NOT mark RN-3 (unchanged idna/certifi dependency bounds) or RN-4 (docstring update) as breaking=true.",
            ],
            "expected_breaking_line_ids": ["RN-1", "RN-2"],
            "non_breaking_trap_line_ids": ["RN-3", "RN-4"],
            "must_include_tokens": ["CVE-2024-35195", "CVE-2024-37891", "Proxy-Authorization", "v2.32.2"],
            "expected_changed_files": ["net_transport/adapters.py", "net_transport/redirects.py"],
            "expected_seed_nodes": [
                "net_transport/adapters.py::TLSAdapter::get_connection_with_tls_context",
                "net_transport/redirects.py::strip_sensitive_redirect_headers",
            ],
            "expected_affected_callers": [
                "clients/artifact_fetcher.py::download_release_tarball",
                "clients/mirror_sync.py::follow_mirror_redirect",
            ],
            "expected_selected_tests": [
                "test_download_release_tarball_verify_key",
                "test_follow_mirror_redirect_strips_proxy_auth",
            ],
            "excluded_unrelated_tests": ["test_parse_cookie_pair"],
        },
    },
]


def main() -> None:
    if SAMPLES_DIR.exists():
        shutil.rmtree(SAMPLES_DIR)
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    for sample in SAMPLES:
        sdir = SAMPLES_DIR / sample["id"]
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "release_notes.md").write_text(sample["release_notes"], encoding="utf-8", newline="\n")
        patch_text = make_git_diff(sample["before_files"], sample["after_files"])
        (sdir / "patch.diff").write_text(patch_text, encoding="utf-8", newline="\n")
        gt = {
            "sample_id": sample["id"],
            "project": sample["project"],
            "from_version": sample["from_version"],
            "to_version": sample["to_version"],
            "release_url": sample["release_url"],
            "license": sample["license"],
            **sample["ground_truth"],
        }
        (sdir / "ground_truth.json").write_text(
            json.dumps(gt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        repo_dir = sdir / "repo"
        for rel, content in sample["after_files"].items():
            fp = repo_dir / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8", newline="\n")
        print(f"Seeded {sample['id']} ({len(patch_text.splitlines())} diff lines)")


if __name__ == "__main__":
    main()
