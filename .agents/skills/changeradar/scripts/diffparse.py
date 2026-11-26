# -*- coding: utf-8 -*-
"""diffparse.py — git diff → 变更行 → 函数映射（Day2 完整实现）。

输入：--diff <file> 或 stdin；或 --range A..B --repo <path>；可选 --graph <callgraph.json>
输出 data：{mode, changes[], commits[]}
  changes: {file, change_type, lines[], functions[{name,node_id,line_range}], unmapped_lines[]}
退出码：0=正常 / 1=部分映射失败 / 2=空diff或格式不可识别

Day2 改进：联动 callgraph 做 functions[].node_id 真实映射（不再全 null 兜底）。
"""
import argparse, json, os, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _envelope import envelope, emit, STATUS_OK, STATUS_PARTIAL, STATUS_ERROR, EXIT_OK, EXIT_PARTIAL, EXIT_ERROR, err

TOOL = "diffparse"

# 包内固定 demo 目录（唯一允许自动重建 git 历史的路径）。
# 用 Path.resolve() 比对，拒绝符号链接逃逸到包外。
_PKG_ROOT = Path(__file__).resolve().parent.parent
_DEMO_DIR = (_PKG_ROOT / "fixtures" / "demo_repo").resolve()

HUNK_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")
FILE_HDR = re.compile(r"^\+\+\+\s+b?/?(.*)$")


def parse_diff(text):
    """解析 unified diff 文本 → changes 列表（不含函数映射，node_id 留 null）。"""
    changes = []
    cur = None
    new_line = 0
    for line in text.splitlines():
        m = FILE_HDR.match(line)
        if m:
            if cur:
                changes.append(cur)
            path = m.group(1)
            if path == "/dev/null":
                path = None
            cur = {"file": path, "change_type": "modified", "lines": [], "functions": [], "unmapped_lines": []}
            new_line = 0
            continue
        m = HUNK_RE.match(line)
        if m:
            new_line = int(m.group(3))
            continue
        if cur is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            if cur["lines"] and cur["lines"][-1][1] == new_line - 1:
                cur["lines"][-1][1] = new_line
            else:
                cur["lines"].append([new_line, new_line])
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            pass
        else:
            new_line += 1
    if cur:
        changes.append(cur)
    return [c for c in changes if c["file"]]


def _build_func_index(graph_data):
    """从 callgraph JSON 构建 {file: [(node_id, name, line_range, kind)]}，按特异性排序（method/function 优先于 class/module）。"""
    index = {}
    kind_priority = {"method": 0, "function": 0, "class": 1, "module": 2}
    for n in graph_data.get("nodes", []):
        f = n.get("file")
        if not f:
            continue
        if f not in index:
            index[f] = []
        index[f].append({
            "node_id": n["id"],
            "name": n["name"],
            "line_range": n.get("line_range", [0, 0]),
            "kind": n.get("kind", "function"),
        })
    # Sort by kind priority (innermost first), then by line_range size (smallest first)
    for f in index:
        index[f].sort(key=lambda x: (kind_priority.get(x["kind"], 9),
                                      x["line_range"][1] - x["line_range"][0]))
    return index


def _map_functions(changes, graph_data):
    """将 changes 里的 lines 映射到 callgraph 函数节点，填充 functions[].node_id。"""
    func_index = _build_func_index(graph_data) if graph_data else {}
    for c in changes:
        f = c["file"]
        candidates = func_index.get(f, [])
        mapped_ranges = set()
        c["functions"] = []
        c["unmapped_lines"] = []
        for line_range in c["lines"]:
            matched = False
            for cand in candidates:
                lr = cand["line_range"]
                # Check if the changed line range falls within the function's line range
                if line_range[0] >= lr[0] and line_range[1] <= lr[1]:
                    key = cand["node_id"]
                    if key not in mapped_ranges:
                        mapped_ranges.add(key)
                        c["functions"].append({
                            "name": cand["name"],
                            "node_id": cand["node_id"],
                            "line_range": lr,
                        })
                    matched = True
                    break
            if not matched:
                c["unmapped_lines"].append(line_range)
    return changes


def run_diff(text, graph_data=None):
    changes = parse_diff(text)
    if not changes:
        return envelope(TOOL, STATUS_ERROR, {"mode": "diff", "changes": [], "commits": []},
                        [err("EMPTY_DIFF", "未解析出任何变更")]), EXIT_ERROR
    if graph_data:
        changes = _map_functions(changes, graph_data)
        has_unmapped = any(c["unmapped_lines"] for c in changes)
        status = STATUS_PARTIAL if has_unmapped else STATUS_OK
        code = EXIT_PARTIAL if has_unmapped else EXIT_OK
        payload = envelope(TOOL, status, {"mode": "diff", "changes": changes, "commits": []})
    else:
        # No graph: node_id 映射降级为 null，impact 将退化为模块级 seed（精度降级）。
        # 显式警告（审查官 Medium 项）：stderr + JSON errors 双通道，避免编排层静默漏传 --graph。
        for c in changes:
            c["unmapped_lines"] = list(c["lines"])
        sys.stderr.write("[diffparse] WARNING: 未传 --graph，functions[].node_id 降级为 null，"
                         "impact 将退化为模块级 seed（精度降级）。建议编排层 checklist Step 3 携带 --graph。\n")
        payload = envelope(TOOL, STATUS_OK, {"mode": "diff", "changes": changes, "commits": []},
                           [err("NO_GRAPH",
                                "未传 --graph：functions[].node_id 降级为 null，impact 退化为模块级 seed")])
        code = EXIT_OK
    return payload, code


def _ensure_git_history(repo):
    """确保 repo 下有 .git；缺则按合规策略处理。

    v5 合规策略（平台审核要求）：绝不自动执行用户仓库路径下的任意 shell 脚本。
    - repo 经 Path.resolve() 解析后**严格等于包内固定 demo 目录**
      (fixtures/demo_repo) 时，才允许自动调 rebuild_history.sh 重建 demo
      历史（保证评审照 README 跑 demo 仍一键可复现）；
    - 其余路径缺 .git → 直接报错退出并打印手动初始化指引，零自动执行。

    返回 (ok: bool, err_msg: str or None)。
    """
    git_dir = os.path.join(repo, ".git")
    if os.path.isdir(git_dir):
        return True, None

    try:
        resolved_repo = Path(repo).resolve()
    except Exception:
        return False, "无法解析 repo 路径: {0}".format(repo)

    # 严格限定：仅包内固定 demo 目录允许自动重建
    if resolved_repo != _DEMO_DIR:
        msg = (
            "目标仓库缺 .git 目录。为合规起见，本工具不会自动执行仓库内脚本。\n"
            "请手动初始化 git 历史后再重试 commit-range 模式：\n"
            "  cd {repo} && bash rebuild_history.sh   # 若仓库提供该脚本\n"
            "  或  git init && git add . && git commit -m 'init'\n"
        ).format(repo=repo)
        return False, msg

    # demo 目录：允许自动重建
    rebuild = os.path.join(repo, "rebuild_history.sh")
    if not os.path.isfile(rebuild):
        return False, "demo 目录缺少 rebuild_history.sh，无法自动重建"
    try:
        subprocess.run(["bash", "rebuild_history.sh"], capture_output=True,
                       text=True, timeout=30, cwd=os.path.abspath(repo))
    except Exception as e:
        return False, "rebuild_history.sh 执行失败: {0}".format(e)
    if not os.path.isdir(git_dir):
        return False, "rebuild_history.sh 执行后仍无 .git 目录"
    return True, None


def run_range(repo, rng, graph_data=None):
    ok, gh_err = _ensure_git_history(repo)
    if not ok:
        sys.stderr.write("[diffparse] ERROR: {0}\n".format(gh_err))
        return envelope(TOOL, STATUS_ERROR, {},
                        [err("NO_GIT_HISTORY", gh_err)]), EXIT_ERROR
    try:
        out = subprocess.run(["git", "-C", repo, "diff", "--unified=3", rng],
                             capture_output=True, text=True, timeout=30)
    except Exception as e:
        return envelope(TOOL, STATUS_ERROR, {}, [err("GIT_FAIL", str(e))]), EXIT_ERROR
    if out.returncode != 0:
        return envelope(TOOL, STATUS_ERROR, {}, [err("GIT_FAIL", out.stderr.strip())]), EXIT_ERROR
    payload, code = run_diff(out.stdout, graph_data)
    if payload["status"] != STATUS_ERROR:
        payload["data"]["mode"] = "commit-range"
        log = subprocess.run(["git", "-C", repo, "log", "--oneline", rng],
                             capture_output=True, text=True, timeout=30)
        commits = []
        for ln in log.stdout.splitlines():
            parts = ln.split(" ", 1)
            if len(parts) == 2:
                commits.append({"sha": parts[0], "subject": parts[1]})
        payload["data"]["commits"] = commits
    return payload, code


def self_check():
    # Test basic diff parsing
    sample = "diff --git a/a.py b/a.py\nindex 1..2 100644\n--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,3 @@\n x = 1\n+y = 2\n z = 3\n"
    payload, code = run_diff(sample)
    assert payload["status"] == STATUS_OK
    assert payload["data"]["changes"][0]["file"] == "a.py"
    # Test with graph mapping
    graph = {"nodes": [
        {"id": "a.py::foo", "name": "foo", "kind": "function", "file": "a.py", "line_range": [1, 5]},
        {"id": "a.py::<module>", "name": "a.py", "kind": "module", "file": "a.py", "line_range": [1, 10]},
    ]}
    payload, code = run_diff(sample, graph)
    assert payload["status"] == STATUS_OK
    funcs = payload["data"]["changes"][0]["functions"]
    assert len(funcs) == 1
    assert funcs[0]["node_id"] == "a.py::foo"
    assert funcs[0]["name"] == "foo"
    # Test unmapped lines
    sample2 = "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1,1 +1,2 @@\n x\n+y\n"
    payload2, code2 = run_diff(sample2, graph)
    assert payload2["status"] == STATUS_PARTIAL
    assert len(payload2["data"]["changes"][0]["unmapped_lines"]) == 1
    return envelope(TOOL, STATUS_OK, {"self_check": "pass"}), EXIT_OK


def main():
    ap = argparse.ArgumentParser(prog="diffparse.py")
    ap.add_argument("--diff", help="diff 文件路径；省略则读 stdin")
    ap.add_argument("--range", help="commit range A..B")
    ap.add_argument("--repo", help="仓库路径（配合 --range）")
    ap.add_argument("--graph", help="callgraph JSON 路径（用于函数→node_id 映射）")
    ap.add_argument("--self-check", action="store_true", help="自检模式")
    args = ap.parse_args()
    if args.self_check:
        payload, code = self_check()
        emit(payload)
        return code
    # Load graph if provided
    graph_data = None
    if args.graph:
        g = json.load(open(args.graph, "r", encoding="utf-8"))
        graph_data = g.get("data", g)
    if args.range:
        if not args.repo:
            emit(envelope(TOOL, STATUS_ERROR, {}, [err("MISSING_ARG", "--range 需要 --repo")]))
            return EXIT_ERROR
        payload, code = run_range(args.repo, args.range, graph_data)
    else:
        if args.diff:
            text = open(args.diff, "r", encoding="utf-8").read()
        else:
            text = sys.stdin.read()
        if not text.strip():
            emit(envelope(TOOL, STATUS_ERROR, {"mode": "diff", "changes": [], "commits": []},
                          [err("EMPTY_DIFF", "输入为空")]))
            return EXIT_ERROR
        payload, code = run_diff(text, graph_data)
    emit(payload)
    return code


if __name__ == "__main__":
    sys.exit(main())
