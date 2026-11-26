# -*- coding: utf-8 -*-
"""propagate.py 单测占位。Day2 编码后补全断言。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


def test_self_check():
    """每个脚本 --self-check 必须通过。"""
    import subprocess
    here = os.path.dirname(__file__)
    script = os.path.join(here, "..", "scripts", "propagate.py")
    r = subprocess.run([sys.executable, script, "--self-check"], capture_output=True, text=True)
    assert r.returncode == 0, f"propagate self-check failed: {r.stderr}"
