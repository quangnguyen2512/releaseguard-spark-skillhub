# -*- coding: utf-8 -*-
"""stacktrace.py（Day3）— 报错栈 → 调用图节点映射 + 反向根因回溯。

输入：报错栈文本（stdin）+ callgraph JSON（--graph）；可选 --changes <diffparse.json> 标记最近变更函数。
处理（对齐 reference.md §4 已冻结契约）：
  1. 栈帧正则解析（Traceback / File "..." / line N / in funcname）
  2. 非 Python 栈特征检测（Java `at com.` / Go `goroutine` / `.go:`）→ 拒收
  3. 过滤项目外帧（site-packages / dist-packages / <frozen ...> / 解释器内建）
  4. 每帧 file+func → callgraph node_id 映射
  5. 标记 last_project_frame（栈底第一帧项目内代码）
  6. 反向 BFS：从 last_project_frame 沿反向边回溯 N 层（--max-distance，默认 3）
  7. 根因候选排序：last_project_frame > nearest_to_seed > changed_recently
  8. 每条候选附 confidence 标签（exact / conservative / unknown）
输出 data：{frames[], root_cause_candidates[], unparsed_lines[], truncation{max_distance, reached}}
退出码：0=全帧映射 / 1=部分帧匹配或栈截断 / 2=无法解析或非 Python 栈
"""
import argparse, json, os, re, sys
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _envelope import envelope, emit, STATUS_OK, STATUS_PARTIAL, STATUS_ERROR, EXIT_OK, EXIT_PARTIAL, EXIT_ERROR, err

TOOL = "stacktrace"

# ---- 正则 ----
FRAME_RE = re.compile(r'File\s+"([^"]+)",\s+line\s+(\d+),\s+in\s+(\S+)')
# 非 Python 栈特征
JAVA_RE = re.compile(r'\bat\s+[a-zA-Z_$][\w$]*(\.[a-zA-Z_$][\w$]*)+\s*\(')
GO_RE = re.compile(r'goroutine\s+\d+\s+\[|\.go:\d+')
# 项目外帧路径特征
EXTERNAL_MARKERS = ("site-packages", "dist-packages", "<frozen ", "<string>", "runpy.py", "importlib")
# 栈截断标记
TRUNC_MARKERS = ("...(truncated)", "... (truncated)", "truncated)", "[Previous line repeated")


def _is_external(file_path):
    p = file_path.replace("\\", "/")
    return any(m in p for m in EXTERNAL_MARKERS)


def _file_match(node_file, frame_file):
    """node_file（项目相对路径）是否匹配 frame_file（可能绝对路径）。"""
    if not node_file or not frame_file:
        return False
    nf = node_file.replace("\\", "/")
    ff = frame_file.replace("\\", "/")
    if nf == ff:
        return True
    # 相对路径作为后缀匹配（frame 可能是 /abs/project/services/order_service.py）
    return ff.endswith("/" + nf) or ff.endswith(nf)


def _map_frame(fr, nodes_by_file):
    """将一帧映射到 callgraph node_id。返回 (node_id|None, matched:bool)。"""
    if _is_external(fr["file"]):
        return None, False
    # func 名为 <module> 时匹配 module 节点
    candidates = nodes_by_file.get(fr["file"], [])
    if not candidates:
        # 后缀宽松匹配：node_file 是 frame_file 的后缀
        for nfile, ns in nodes_by_file.items():
            if _file_match(nfile, fr["file"]):
                candidates = ns
                break
    for n in candidates:
        # <module> 帧匹配 module 节点（module 节点 name 是 relpath，非 "<module>"）
        if fr["func"] == "<module>" and n.get("kind") == "module":
            return n["id"], True
        if n.get("name") == fr["func"]:
            return n["id"], True
        # method 节点 name 是方法名；func 也可能是 ClassName.method（少见），做兜底匹配
        if "." in fr["func"] and n.get("name") == fr["func"].split(".")[-1]:
            return n["id"], True
    return None, False


def run(text, graph_data, changes_data=None, max_distance=3):
    lines = text.splitlines()
    frames = []
    unparsed_lines = []
    has_traceback = False
    truncation_detected = False

    # 非 Python 栈检测（整体文本扫描）
    non_py_hits = []
    for ln in lines:
        if JAVA_RE.search(ln):
            non_py_hits.append(("java", ln.strip()))
        if GO_RE.search(ln):
            non_py_hits.append(("go", ln.strip()))
    # 有 Java/Go 特征且无任何 Python File 帧 → 拒收
    py_frame_lines = [l for l in lines if FRAME_RE.search(l)]
    if non_py_hits and not py_frame_lines:
        langs = sorted({h[0] for h in non_py_hits})
        return (envelope(TOOL, STATUS_ERROR,
                         {"frames": [], "root_cause_candidates": [], "unparsed_lines": [],
                          "truncation": {"max_distance": max_distance, "reached": False}},
                         [err("NON_PYTHON_STACK",
                              "检测到 %s 栈特征，当前仅支持 Python" % "/".join(langs))]),
                EXIT_ERROR)

    # 逐行解析
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if "Traceback" in s:
            has_traceback = True
            continue
        if s.startswith("During handling") or s.startswith("The above exception"):
            continue
        if any(m in s for m in TRUNC_MARKERS):
            truncation_detected = True
            unparsed_lines.append(s)
            continue
        m = FRAME_RE.search(ln)
        if m:
            frames.append({
                "file": m.group(1), "line": int(m.group(2)),
                "func": m.group(3), "node_id": None, "matched": False,
                "raw": s,
            })
            continue
        # 异常类型行（如 ValueError: xxx）——非帧、非未解析
        if re.match(r'^[A-Za-z_][\w.]*Error\s*:', s) or re.match(r'^[A-Za-z_][\w.]*Exception\s*:', s):
            continue
        # 普通代码缩进行（Traceback 内源码片段）跳过
        if s.startswith("return ") or s.startswith("raise ") or s.startswith("self.") or s.startswith("if ") or s.endswith(")"):
            continue
        unparsed_lines.append(s)

    if not frames:
        return (envelope(TOOL, STATUS_ERROR,
                         {"frames": [], "root_cause_candidates": [], "unparsed_lines": unparsed_lines,
                          "truncation": {"max_distance": max_distance, "reached": False}},
                         [err("NO_FRAMES", "未解析出栈帧")]),
                EXIT_ERROR)

    # 构建 file → nodes 索引（仅 function/method/module 节点）
    nodes_by_file = defaultdict(list)
    rev = defaultdict(list)  # to -> [(from, confidence)]
    test_nodes = set()
    for n in graph_data.get("nodes", []):
        nodes_by_file[n.get("file")].append(n)
        if n.get("is_test"):
            test_nodes.add(n["id"])
    for e in graph_data.get("edges", []):
        rev[e["to"]].append((e["from"], e.get("confidence", "exact")))

    # 最近变更函数集合（可选，来自 diffparse --changes）
    changed_nodes = set()
    if changes_data:
        for c in changes_data.get("changes", []):
            for fn in c.get("functions", []):
                nid = fn.get("node_id")
                if nid:
                    changed_nodes.add(nid)

    # 帧映射
    matched = 0
    project_frames = 0
    for fr in frames:
        if _is_external(fr["file"]):
            continue
        project_frames += 1
        nid, ok = _map_frame(fr, nodes_by_file)
        if ok:
            fr["node_id"] = nid
            fr["matched"] = True
            matched += 1

    # last_project_frame：栈底第一帧项目内代码（reversed 取首个 matched）
    last_pf_node = None
    for fr in reversed(frames):
        if fr["matched"]:
            last_pf_node = fr["node_id"]
            break

    candidates = []
    seen = set()

    def _confidence_for(distance):
        if distance == 0:
            return "exact"
        if distance <= 2:
            return "conservative"
        return "unknown"

    # 1) last_project_frame
    if last_pf_node:
        candidates.append({
            "node_id": last_pf_node, "reason": "last_project_frame",
            "confidence": "exact", "distance": 0,
        })
        seen.add(last_pf_node)

    # 2) nearest_to_seed：反向 BFS 回溯
    reached = False
    if last_pf_node:
        dq = deque()
        dq.append((last_pf_node, 0))
        while dq:
            cur, dist = dq.popleft()
            if dist >= max_distance:
                reached = True
                continue
            for caller, econf in rev.get(cur, []):
                if caller in test_nodes:
                    continue
                nd = dist + 1
                if caller not in seen:
                    candidates.append({
                        "node_id": caller, "reason": "nearest_to_seed",
                        "confidence": _confidence_for(nd), "distance": nd,
                    })
                    seen.add(caller)
                    dq.append((caller, nd))
                elif nd <= 2:
                    # 已存在但更近 → 升级 reason/confidence（取更优）
                    for c in candidates:
                        if c["node_id"] == caller and nd < c["distance"]:
                            c["distance"] = nd
                            c["confidence"] = _confidence_for(nd)
                            break

    # 3) changed_recently：命中最近变更的候选升级
    if changed_nodes:
        for c in candidates:
            if c["node_id"] in changed_nodes and c["reason"] == "nearest_to_seed":
                c["reason"] = "changed_recently"
                c["confidence"] = "exact"

    # 排序：last_project_frame(0) → changed_recently → nearest_to_seed；同 reason 按 distance
    reason_order = {"last_project_frame": 0, "changed_recently": 1, "nearest_to_seed": 2}
    candidates.sort(key=lambda c: (reason_order.get(c["reason"], 9), c["distance"]))

    # 截断状态
    truncation = {"max_distance": max_distance, "reached": reached or truncation_detected}
    data = {
        "frames": frames,
        "root_cause_candidates": candidates,
        "unparsed_lines": unparsed_lines,
        "truncation": truncation,
    }

    if matched == 0 and project_frames > 0:
        # 有项目帧但全部未映射到图 → 部分结果
        status = STATUS_PARTIAL
        code = EXIT_PARTIAL
        data_errors = [err("NO_MATCH", "栈帧未映射到调用图节点（栈与项目不匹配？）")]
        payload = envelope(TOOL, status, data, data_errors)
    elif matched < project_frames or truncation_detected:
        status = STATUS_PARTIAL
        code = EXIT_PARTIAL
        payload = envelope(TOOL, status, data,
                           [err("PARTIAL_MATCH", "部分帧未映射或栈截断")] if (matched < project_frames) else [])
    else:
        status = STATUS_OK
        code = EXIT_OK
        payload = envelope(TOOL, status, data)
    return payload, code


def self_check():
    text = ('Traceback (most recent call last):\n'
            '  File "a.py", line 5, in g\n    f()\n'
            '  File "a.py", line 2, in f\n    return 1\n'
            'ValueError: bad')
    g = {"nodes": [
        {"id": "a.py::f", "name": "f", "kind": "function", "file": "a.py", "line_range": [1, 2]},
        {"id": "a.py::g", "name": "g", "kind": "function", "file": "a.py", "line_range": [4, 5]},
    ], "edges": [{"from": "a.py::g", "to": "a.py::f", "type": "call", "confidence": "exact",
                  "site": {"file": "a.py", "line": 5}}]}
    payload, code = run(text, g)
    assert code == EXIT_OK, f"expected exit 0 got {code}: {payload}"
    assert payload["data"]["frames"][0]["matched"]
    # last_project_frame = 栈底第一帧项目内 = a.py::f（reversed 取首个 matched）
    cands = payload["data"]["root_cause_candidates"]
    assert cands, "candidates empty"
    assert cands[0]["node_id"] == "a.py::f"
    assert cands[0]["reason"] == "last_project_frame"
    # 反向 BFS：g 是 f 的调用方 → nearest_to_seed
    assert any(c["node_id"] == "a.py::g" and c["reason"] == "nearest_to_seed" for c in cands)
    assert payload["data"]["truncation"]["max_distance"] == 3
    return envelope(TOOL, STATUS_OK, {"self_check": "pass"}), EXIT_OK


def main():
    ap = argparse.ArgumentParser(prog="stacktrace.py")
    ap.add_argument("--graph", help="callgraph JSON 路径（必填）")
    ap.add_argument("--changes", help="diffparse JSON 路径（可选，标记最近变更函数）")
    ap.add_argument("--max-distance", type=int, default=3, help="反向回溯最大层数（默认 3）")
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()
    if args.self_check:
        payload, code = self_check()
        emit(payload)
        return code
    text = sys.stdin.read()
    if not text.strip():
        emit(envelope(TOOL, STATUS_ERROR,
                      {"frames": [], "root_cause_candidates": [], "unparsed_lines": [],
                       "truncation": {"max_distance": args.max_distance, "reached": False}},
                      [err("EMPTY", "stdin 为空")]))
        return EXIT_ERROR
    if not args.graph:
        emit(envelope(TOOL, STATUS_ERROR, {},
                      [err("MISSING_ARG", "--graph 必填")]))
        return EXIT_ERROR
    g = json.load(open(args.graph, "r", encoding="utf-8"))
    gd = g.get("data", g)
    cd = None
    if args.changes:
        c = json.load(open(args.changes, "r", encoding="utf-8"))
        cd = c.get("data", c)
    payload, code = run(text, gd, cd, args.max_distance)
    emit(payload)
    return code


if __name__ == "__main__":
    sys.exit(main())
