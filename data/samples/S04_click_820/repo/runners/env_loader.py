from cli_kit.options import resolve_envvar_value


def load_runtime_flags(environ):
    region = resolve_envvar_value(environ, "CLOUD_REGION")
    return {"region": region or "us-east-1"}
