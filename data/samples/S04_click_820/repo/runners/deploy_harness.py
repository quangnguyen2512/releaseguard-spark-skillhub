from cli_kit.testing_harness import CliRunner


def invoke_deploy_cli(target_env):
    runner = CliRunner(charset="utf-8", env={"DEPLOY_ENV": target_env})
    return runner.run_command("deploy")
