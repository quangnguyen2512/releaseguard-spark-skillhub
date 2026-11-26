from api_core.params import build_query_validator


def search_items_endpoint(raw_sku):
    rule = build_query_validator(pattern=r"^[A-Z0-9_-]+$", max_length=32)
    matched = bool(rule["compiled"].match(raw_sku))
    return {"sku": raw_sku, "valid": matched}
