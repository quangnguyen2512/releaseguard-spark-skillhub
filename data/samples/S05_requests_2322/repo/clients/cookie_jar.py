def parse_cookie_pair(header_val):
    k, _, v = header_val.partition("=")
    return {k.strip(): v.strip()}
