# -*- coding: utf-8 -*-
"""propagate.py — 图传播 + fan-in 截断 + 置信度分档（Day2 完整实现）。

输入：--graph <callgraph.json> --changes <diffparse.json> [--max-distance 3] [--fanin-cap 50]
输出 data：{seeds[], impact[], hubs[], truncation, module_fallback[], confidence_distribution}
退出码：0=有impact / 1=impact为空但有seeds / 2=无seeds

Day2 改进：
- dynamic 模块全函数并入 impact（conservative）
- commit-range 多变更 seeds 合并去重
- 新增 confidence_distribution 聚合字段（按裁决落点在 propagate 输出）
"""
import argparse, json, os, sys
from collections import deque, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _envelope import envelope, emit, STATUS_OK, STATUS_PARTIAL, STATUS_ERROR, EXIT_OK, EXIT_PARTIAL, EXIT_ERROR, err

TOOL = "propagate"
RANK = {"exact": 3, "conservative": 2, "unknown": 1}


def _min_conf(a, b):
    return a if RANK[a] <= RANK[b] else b


def run(graph_data, changes_data, max_distance=3, fanin_cap=50):
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    # ---- Build indexes ----
    rev = defaultdict(list)  # to -> [(from, confidence)]
    fan_in = defaultdict(int)
    for e in edges:
        rev[e["to"]].append((e["from"], e.get("confidence", "exact")))
        fan_in[e["to"]] += 1

    # Dynamic module detection: collect files that are dynamic
    dynamic_files = set()
    file_funcs = defaultdict(list)  # file -> [node_ids of functions/methods in that file]
    test_nodes = set()  # node_ids that are test nodes
    for n in nodes:
        if n.get("dynamic") and n.get("kind") == "module":
            dynamic_files.add(n["file"])
        if n.get("kind") in ("function", "method"):
            file_funcs[n.get("file")].append(n["id"])
        if n.get("is_test"):
            test_nodes.add(n["id"])

    # ---- Seeds: changes.functions.node_id (deduped) + module fallback ----
    seeds = set()
    seed_sources = {}  # node_id -> [seed source descriptions]
    for c in changes_data.get("changes", []):
        for fn in c.get("functions", []):
            if fn.get("node_id"):
                seeds.add(fn["node_id"])
                seed_sources.setdefault(fn["node_id"], []).append(f"diff:{c['file']}::{fn['name']}")
        # Module fallback: if file has changes but no function mapping, add module node
        if not any(fn.get("node_id") for fn in c.get("functions", [])):
            for n in nodes:
                if n.get("kind") == "module" and n.get("file") == c.get("file"):
                    seeds.add(n["id"])
                    seed_sources.setdefault(n["id"], []).append(f"module_fallback:{c['file']}")

    if not seeds:
        return envelope(TOOL, STATUS_ERROR, {
            "seeds": [], "impact": [], "hubs": [],
            "truncation": {"max_distance": max_distance, "fanin_cap": fanin_cap,
                           "hit_distance_cap": 0, "hit_fanin_cap": 0},
            "module_fallback": [], "confidence_distribution": {"exact": 0, "conservative": 0, "unknown": 0}
        }, [err("NO_SEEDS", "变更未映射到任何调用图节点")]), EXIT_ERROR

    # ---- Reverse BFS ----
    impact = {}
    hubs = []
    hub_set = set()
    hit_fanin = 0

    for s in seeds:
        impact[s] = {
            "node_id": s, "distance": 0, "path": [s],
            "fan_in": fan_in.get(s, 0), "confidence": "exact",
            "truncated": False, "is_seed": True,
        }

    dq = deque(seeds)
    while dq:
        cur = dq.popleft()
        rec = impact[cur]
        if rec["distance"] >= max_distance:
            continue
        # Fan-in check: if current node is a hub, don't expand its callers
        if fan_in.get(cur, 0) > fanin_cap:
            if cur not in hub_set:
                hub_set.add(cur)
                callers = [c for c, _ in rev.get(cur, [])][:10]
                hubs.append({"node_id": cur, "fan_in": fan_in[cur], "top_callers": callers})
            hit_fanin += 1
            continue
        for caller, econf in rev.get(cur, []):
            # Skip test nodes: they're callers but shouldn't be in the impact
            if caller in test_nodes:
                continue
            conf = _min_conf(rec["confidence"], econf)
            new_dist = rec["distance"] + 1
            if caller in impact:
                # Update if shorter path or higher confidence
                existing = impact[caller]
                if new_dist < existing["distance"]:
                    existing["distance"] = new_dist
                    existing["path"] = rec["path"] + [caller]
                    existing["confidence"] = conf
                    existing["truncated"] = new_dist >= max_distance
                    dq.append(caller)
                elif new_dist == existing["distance"] and RANK[conf] > RANK[existing["confidence"]]:
                    existing["confidence"] = conf
                continue
            impact[caller] = {
                "node_id": caller, "distance": new_dist,
                "path": rec["path"] + [caller],
                "fan_in": fan_in.get(caller, 0),
                "confidence": conf,
                "truncated": new_dist >= max_distance,
                "is_seed": caller in seeds,
            }
            dq.append(caller)

    # ---- Dynamic module expansion ----
    # If any node in a dynamic module is in the impact, add ALL functions of that module
    module_fallback = []
    impact_files = set()
    for nid in impact:
        # Extract file from node_id
        if "::" in nid:
            impact_files.add(nid.split("::")[0])
    for dyn_file in dynamic_files:
        if dyn_file in impact_files:
            module_fallback.append(dyn_file)
            for func_nid in file_funcs.get(dyn_file, []):
                if func_nid not in impact:
                    impact[func_nid] = {
                        "node_id": func_nid, "distance": max_distance,
                        "path": [func_nid], "fan_in": fan_in.get(func_nid, 0),
                        "confidence": "conservative", "truncated": True,
                        "is_seed": False, "dynamic_expansion": True,
                    }

    # ---- Confidence distribution ----
    conf_dist = {"exact": 0, "conservative": 0, "unknown": 0}
    for imp in impact.values():
        conf = imp["confidence"]
        if conf in conf_dist:
            conf_dist[conf] += 1

    # ---- Build output ----
    impact_list = sorted(impact.values(), key=lambda x: (x["distance"], x["node_id"]))
    trunc = {
        "max_distance": max_distance, "fanin_cap": fanin_cap,
        "hit_distance_cap": sum(1 for i in impact_list if i["truncated"] and not i.get("dynamic_expansion")),
        "hit_fanin_cap": hit_fanin,
    }
    data = {
        "seeds": sorted(seeds),
        "impact": impact_list,
        "hubs": hubs,
        "truncation": trunc,
        "module_fallback": sorted(set(module_fallback)),
        "confidence_distribution": conf_dist,
    }

    if not impact_list:
        return envelope(TOOL, STATUS_PARTIAL, data, [err("NO_IMPACT", "seeds 存在但未传播出影响面")]), EXIT_PARTIAL

    return envelope(TOOL, STATUS_OK, data), EXIT_OK


def self_check():
    g = {"nodes": [
        {"id": "a.py::f", "kind": "function", "file": "a.py", "line_range": [1, 2]},
        {"id": "a.py::g", "kind": "function", "file": "a.py", "line_range": [3, 4]},
        {"id": "a.py::<module>", "kind": "module", "file": "a.py", "line_range": [1, 4]},
    ], "edges": [{"from": "a.py::g", "to": "a.py::f", "type": "direct", "confidence": "exact", "site": {"file": "a.py", "line": 3}}]}
    c = {"changes": [{"file": "a.py", "functions": [{"name": "f", "node_id": "a.py::f", "line_range": [1, 2]}], "unmapped_lines": []}]}
    payload, code = run(g, c)
    assert payload["status"] == STATUS_OK
    assert "a.py::g" in [i["node_id"] for i in payload["data"]["impact"]]
    # Check confidence_distribution
    cd = payload["data"]["confidence_distribution"]
    assert cd["exact"] >= 2  # f (seed) + g (direct)
    # Test dynamic module expansion
    g2 = {"nodes": [
        {"id": "dyn.py::<module>", "kind": "module", "file": "dyn.py", "line_range": [1, 10], "dynamic": True},
        {"id": "dyn.py::f", "kind": "function", "file": "dyn.py", "line_range": [1, 5]},
        {"id": "dyn.py::g", "kind": "function", "file": "dyn.py", "line_range": [6, 10]},
    ], "edges": []}
    c2 = {"changes": [{"file": "dyn.py", "functions": [{"name": "f", "node_id": "dyn.py::f", "line_range": [1, 5]}], "unmapped_lines": []}]}
    payload2, code2 = run(g2, c2)
    impact_ids = [i["node_id"] for i in payload2["data"]["impact"]]
    assert "dyn.py::g" in impact_ids, "Dynamic module expansion should add dyn.py::g"
    assert payload2["data"]["module_fallback"] == ["dyn.py"]
    return envelope(TOOL, STATUS_OK, {"self_check": "pass"}), EXIT_OK


def main():
    ap = argparse.ArgumentParser(prog="propagate.py")
    ap.add_argument("--graph", required=False, help="callgraph JSON 路径")
    ap.add_argument("--changes", required=False, help="diffparse JSON 路径")
    ap.add_argument("--max-distance", type=int, default=3)
    ap.add_argument("--fanin-cap", type=int, default=50)
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()
    if args.self_check:
        payload, code = self_check()
        emit(payload)
        return code
    if not args.graph or not args.changes:
        emit(envelope(TOOL, STATUS_ERROR, {}, [err("MISSING_ARG", "--graph 和 --changes 必填")]))
        return EXIT_ERROR
    g = json.load(open(args.graph, "r", encoding="utf-8"))
    c = json.load(open(args.changes, "r", encoding="utf-8"))
    gd = g.get("data", g)
    cd = c.get("data", c)
    payload, code = run(gd, cd, args.max_distance, args.fanin_cap)
    emit(payload)
    return code


if __name__ == "__main__":
    sys.exit(main())
