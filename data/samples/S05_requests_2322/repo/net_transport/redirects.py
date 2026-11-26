def strip_sensitive_redirect_headers(headers, same_origin, trust_env_redirects=False):
    cleaned = dict(headers)
    if not same_origin and not trust_env_redirects:
        cleaned.pop("Proxy-Authorization", None)
        cleaned.pop("Authorization", None)
    return cleaned
