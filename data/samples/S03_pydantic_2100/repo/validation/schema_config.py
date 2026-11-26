def compile_model_config(config_dict):
    if "allow_mutation" in config_dict:
        raise ValueError("allow_mutation is removed; use frozen=True")
    return {"frozen": bool(config_dict.get("frozen", False)), "extra": config_dict.get("extra", "ignore")}
