import re


def build_query_validator(pattern=None, max_length=64):
    compiled = re.compile(pattern) if pattern else None
    return {"pattern": pattern, "compiled": compiled, "max_length": max_length}
