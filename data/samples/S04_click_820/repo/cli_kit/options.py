def resolve_envvar_value(env_map, key):
    raw = env_map.get(key)
    if raw is None or raw == "":
        return None
    return raw
