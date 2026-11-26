class CliRunner:
    def __init__(self, charset="utf-8", env=None):
        self.charset = charset
        self.env = env or {}

    def run_command(self, cmd_name):
        return {"cmd": cmd_name, "stdout": "ok", "stderr": ""}
