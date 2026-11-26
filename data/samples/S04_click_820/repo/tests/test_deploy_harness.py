from runners.deploy_harness import invoke_deploy_cli


def test_invoke_deploy_cli_runner():
    res = invoke_deploy_cli("staging")
    assert res["stdout"] == "ok"
