# -*- coding: utf-8 -*-
"""stacktrace.py 单测（Day3 填实）。覆盖：栈清晰 / 栈与项目不匹配 C5 / 栈截断 / 非 Python 栈拒收。"""
import json, os, subprocess, sys

HERE = os.path.dirname(__file__)
SCRIPT = os.path.join(HERE, "..", "scripts", "stacktrace.py")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))


def _run(text, graph=None, changes=None, max_distance=3):
    p = subprocess.run([sys.executable, SCRIPT, "--max-distance", str(max_distance)],
                       input=text, capture_output=True, text=True)
    return p


def _graph():
    return {"nodes": [
        {"id": "a.py::f", "name": "f", "kind": "function", "file": "a.py", "line_range": [1, 2]},
        {"id": "a.py::g", "name": "g", "kind": "function", "file": "a.py", "line_range": [4, 5]},
    ], "edges": [{"from": "a.py::g", "to": "a.py::f", "type": "call", "confidence": "exact",
                  "site": {"file": "a.py", "line": 5}}]}


def test_self_check():
    r = subprocess.run([sys.executable, SCRIPT, "--self-check"], capture_output=True, text=True)
    assert r.returncode == 0, f"self-check failed: {r.stderr}"
    payload = json.loads(r.stdout)
    assert payload["data"]["self_check"] == "pass"


def test_clear_stack():
    """栈清晰：全帧映射，candidates 非空，根因帧命中。"""
    import stacktrace
    text = ('Traceback (most recent call last):\n'
            '  File "a.py", line 5, in g\n    f()\n'
            '  File "a.py", line 2, in f\n    return 1\n'
            'ValueError: bad')
    payload, code = stacktrace.run(text, _graph())
    assert code == 0
    assert payload["data"]["frames"][0]["matched"]
    cands = payload["data"]["root_cause_candidates"]
    assert cands, "candidates empty"
    assert cands[0]["node_id"] == "a.py::f"
    assert cands[0]["reason"] == "last_project_frame"
    assert any(c["node_id"] == "a.py::g" for c in cands)


def test_external_frames_filtered():
    """项目外帧（site-packages）不参与映射，status 仍 ok（项目帧全匹配）。"""
    import stacktrace
    text = ('Traceback (most recent call last):\n'
            '  File "/usr/lib/python3.10/site-packages/requests/sessions.py", line 1, in send\n    x\n'
            '  File "a.py", line 2, in f\n    return 1\n'
            'ConnectionError: timeout')
    payload, code = stacktrace.run(text, _graph())
    assert code == 0
    frames = payload["data"]["frames"]
    assert frames[0]["file"].endswith("sessions.py")
    assert frames[0]["matched"] is False  # site-packages 过滤
    assert frames[1]["matched"] is True


def test_stack_project_mismatch():
    """栈与项目不匹配 C5：有项目帧但无帧映射到图 → partial + NO_MATCH。"""
    import stacktrace
    text = ('Traceback (most recent call last):\n'
            '  File "other.py", line 2, in f\n    return 1\n'
            'RuntimeError: x')
    payload, code = stacktrace.run(text, _graph())
    assert code == 1
    assert payload["data"]["root_cause_candidates"] == []
    assert any(e["code"] == "NO_MATCH" for e in payload["errors"])


def test_truncated_stack():
    """栈截断：含 (truncated) 标记 → status partial。"""
    import stacktrace
    text = ('Traceback (most recent call last):\n'
            '  File "a.py", line 5, in g\n    f()\n'
            '  File "a.py", line 2, in f\n    return 1\n'
            '...(truncated)\n')
    payload, code = stacktrace.run(text, _graph())
    assert code == 1  # 截断 → partial
    assert payload["data"]["truncation"]["reached"] is True


def test_non_python_stack_rejected():
    """非 Python 栈（Java/Go）→ 拒收 exit 2。"""
    import stacktrace
    java = ('Exception in thread "main" java.lang.NullPointerException\n'
            '    at com.foo.Bar.handle(Bar.java:12)\n'
            '    at com.foo.Main.main(Main.java:5)')
    payload, code = stacktrace.run(java, _graph())
    assert code == 2
    assert any(e["code"] == "NON_PYTHON_STACK" for e in payload["errors"])

    go = ('goroutine 1 [running]:\nmain.foo()\n\t/path/main.go:10 +0x20')
    payload2, code2 = stacktrace.run(go, _graph())
    assert code2 == 2


def test_changed_recently_boost():
    """--changes 命中最近变更函数 → nearest_to_seed 升级为 changed_recently。"""
    import stacktrace
    text = ('Traceback (most recent call last):\n'
            '  File "a.py", line 5, in g\n    f()\n'
            '  File "a.py", line 2, in f\n    return 1\n'
            'ValueError: bad')
    changes = {"changes": [{"file": "a.py", "functions": [{"name": "g", "node_id": "a.py::g"}]}]}
    payload, code = stacktrace.run(text, _graph(), changes)
    assert code == 0
    cands = payload["data"]["root_cause_candidates"]
    g_cand = [c for c in cands if c["node_id"] == "a.py::g"][0]
    assert g_cand["reason"] == "changed_recently"
