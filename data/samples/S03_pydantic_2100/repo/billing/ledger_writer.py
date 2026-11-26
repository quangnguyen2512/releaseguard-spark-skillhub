from validation.schema_config import compile_model_config


def append_immutable_entry(raw_cfg, amount_cents):
    cfg = compile_model_config(raw_cfg)
    return {"frozen": cfg["frozen"], "amount_cents": amount_cents}
