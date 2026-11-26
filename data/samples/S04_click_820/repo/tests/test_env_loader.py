from runners.env_loader import load_runtime_flags


def test_load_runtime_flags_empty_envvar():
    cfg = load_runtime_flags({"CLOUD_REGION": ""})
    assert cfg["region"] == "us-east-1"
