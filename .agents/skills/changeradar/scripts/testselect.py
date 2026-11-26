# -*- coding: utf-8 -*-
"""testselect.py — 测试静态耦合映射 + 风险排序（Day2 完整实现）。

输入：--impact <propagate.json> --graph <callgraph.json> --tests <dir>
输出 data：{tests[], metrics{total_tests,selected,compression_ratio,impact_coverage}}
退出码：0=有选中测试 / 1=无测试目录→tests空 / 2=输入异常

Day2 改进：三种 coupling 依据完整实现
- 直调 1.0：测试直接调用 impact 集合中的函数/方法
- 间接 0.5/distance：测试调用的函数在调用图上距 impact 节点 distance d
- 名称相似 0.2：测试名包含 impact 节点的函数名
- 多依据取 max
"""
import argparse, ast, json, os, sys
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _envelope import envelope, emit, STATUS_OK, STATUS_PARTIAL, STATUS_ERROR, EXIT_OK, EXIT_PARTIAL, EXIT_ERROR, err

TOOL = "testselect"

_BUILTINS = {"print", "str", "int", "float", "list", "dict", "set", "tuple", "len", "range",
             "sum", "min", "max", "abs", "round", "sorted", "reversed", "enumerate", "zip",
             "isinstance", "issubclass", "type", "super", "open", "bool", "bytes", "format",
             "input", "assert", "hasattr", "getattr", "setattr", "delattr", "id", "hash"}


def _scan_tests(tests_dir, root=None):
    """扫描测试目录，返回 [{test_file, test_name, calls:set, imports:dict}]。"""
    tests = []
    if not os.path.isdir(tests_dir):
        return tests, False
    for dirpath, _d, files in os.walk(tests_dir):
        for fn in files:
            if (fn.startswith("test_") and fn.endswith(".py")) or fn.endswith("_test.py"):
                ap = os.path.join(dirpath, fn)
                rel = os.path.relpath(ap, tests_dir).replace(os.sep, "/")
                try:
                    src = open(ap, "r", encoding="utf-8").read()
                    tree = ast.parse(src, filename=ap)
                except Exception:
                    continue
                # Parse imports
                imports = {}
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.names[0].name != "*":
                        for alias in node.names:
                            name = alias.asname or alias.name
                            imports[name] = {"module": node.module or "", "symbol": alias.name}
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            name = alias.asname or alias.name.split(".")[0]
                            imports[name] = {"module": alias.name, "symbol": None}
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                        calls = set()
                        local_instances = {}  # var_name → class_name
                        for sub in ast.walk(node):
                            # Track local instance assignments: x = ClassName()
                            if (isinstance(sub, ast.Assign) and len(sub.targets) == 1
                                    and isinstance(sub.targets[0], ast.Name)
                                    and isinstance(sub.value, ast.Call)
                                    and isinstance(sub.value.func, ast.Name)):
                                local_instances[sub.targets[0].id] = sub.value.func.id
                            if isinstance(sub, ast.Call):
                                if isinstance(sub.func, ast.Name):
                                    calls.add(("name", sub.func.id, None))
                                elif isinstance(sub.func, ast.Attribute):
                                    attr = sub.func.attr
                                    val = sub.func.value
                                    if isinstance(val, ast.Name):
                                        if val.id == "self":
                                            calls.add(("self_method", attr, None))
                                        elif val.id in local_instances:
                                            calls.add(("instance_method", attr, local_instances[val.id]))
                                        else:
                                            calls.add(("attr", attr, val.id))
                        tests.append({
                            "test_file": rel, "test_name": node.name,
                            "calls": calls, "imports": imports,
                        })
    return tests, True


def _build_graph_indexes(graph_data):
    """Build helper indexes from callgraph JSON."""
    # node_id → node info
    node_map = {}
    # name → [node_ids]
    name_index = defaultdict(list)
    # class_name → node_id (for classes)
    class_index = {}
    # class_node_id → {method_name: method_node_id}
    class_methods = defaultdict(dict)
    # class_node_id → [base_class_names]
    class_bases = {}
    # file → module dotted path
    file_mod_index = {}

    for n in graph_data.get("nodes", []):
        node_map[n["id"]] = n
        if n.get("kind") != "module":
            name_index[n["name"]].append(n["id"])
        if n.get("kind") == "class":
            class_index[n["name"]] = n["id"]
            class_bases[n["id"]] = n.get("bases") or []
        if n.get("kind") == "method" and n.get("class"):
            class_methods[n["class"]][n["name"]] = n["id"]

    # Build class parent map: class_name → base_class_name (single inheritance)
    class_parent = {}
    for cls_nid, bases in class_bases.items():
        # Find the class name from node_map
        cls_name = node_map.get(cls_nid, {}).get("name")
        if cls_name and bases:
            class_parent[cls_name] = bases[0]  # single inheritance: first base

    # Forward adjacency: from → [to]
    fwd = defaultdict(list)
    for e in graph_data.get("edges", []):
        fwd[e["from"]].append(e["to"])

    return node_map, name_index, class_index, class_methods, class_parent, fwd


def _resolve_test_call(call, imports, name_index, class_index, class_methods, class_parent, mod_index):
    """Resolve a test call to a set of node_ids in the call graph."""
    kind, name, ctx = call
    result = set()
    if kind == "name":
        # Direct function call: check imports first
        if name in imports and name not in _BUILTINS:
            imp = imports[name]
            # Try to find the symbol in the source module
            for nid in name_index.get(imp.get("symbol") or name, []):
                result.add(nid)
        # Also check global name index
        if name not in _BUILTINS:
            for nid in name_index.get(name, []):
                result.add(nid)
        # Constructor call to a class
        if name in class_index:
            cls_nid = class_index[name]
            if "__init__" in class_methods.get(cls_nid, {}):
                result.add(class_methods[cls_nid]["__init__"])
            result.add(cls_nid)
    elif kind == "instance_method":
        # var.method() where var = ClassName()
        cls_name = ctx
        # Walk MRO chain (single inheritance)
        visited = set()
        while cls_name and cls_name not in visited:
            visited.add(cls_name)
            if cls_name in class_index:
                cls_nid = class_index[cls_name]
                if name in class_methods.get(cls_nid, {}):
                    result.add(class_methods[cls_nid][name])
                    break  # found in this class, MRO resolved
            cls_name = class_parent.get(cls_name)
    elif kind == "attr":
        # Check if the value name is an imported module
        if ctx in imports:
            imp = imports[ctx]
            for nid in name_index.get(name, []):
                result.add(nid)
    elif kind == "self_method":
        # self.method() in test - unusual but handle it
        for nid in name_index.get(name, []):
            result.add(nid)
    return result


def _compute_distances(node_ids, impact_ids, fwd):
    """Compute shortest FORWARD distance from each node_id to the nearest impact node.
    Uses only forward edges (callees): test calls X, X calls Y (in impact) → distance 1.
    """
    distances = {}
    for nid in node_ids:
        if nid in impact_ids:
            distances[nid] = 0
            continue
        # BFS forward to find nearest impact node (limited depth)
        visited = {nid}
        dq = deque([(nid, 0)])
        found = None
        while dq:
            cur, d = dq.popleft()
            if d > 5:
                break
            if cur in impact_ids and cur != nid:
                found = d
                break
            for neighbor in fwd.get(cur, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    dq.append((neighbor, d + 1))
        if found is not None:
            distances[nid] = found
    return distances


def run(impact_data, graph_data, tests_dir):
    impact_ids = {i["node_id"] for i in impact_data.get("impact", [])}
    impact_node_names = set()
    for i in impact_data.get("impact", []):
        # Extract function name from node_id
        nid = i["node_id"]
        if "::" in nid:
            parts = nid.split("::")
            if len(parts) >= 2 and parts[-1] != "<module>":
                impact_node_names.add(parts[-1])

    node_map, name_index, class_index, class_methods, class_parent, fwd = _build_graph_indexes(graph_data)

    # Build reverse adjacency for distance computation
    rev = defaultdict(list)
    for e in graph_data.get("edges", []):
        rev[e["to"]].append(e["from"])

    # Build module index from graph nodes
    mod_index = {}
    for n in graph_data.get("nodes", []):
        if n.get("kind") == "module":
            mod_path = n["file"][:-3].replace("/", ".") if n["file"].endswith(".py") else n["file"]
            mod_index[mod_path] = n["file"]

    tests, found = _scan_tests(tests_dir)
    if not found:
        data = {"tests": [], "metrics": {"total_tests": 0, "selected": 0,
                                         "compression_ratio": 0.0, "impact_coverage": 0.0}}
        return envelope(TOOL, STATUS_PARTIAL, data,
                        [err("NO_TESTS_DIR", f"未找到测试目录: {tests_dir}")]), EXIT_PARTIAL

    selected = []
    covered = set()

    for t in tests:
        # Resolve test calls to node_ids
        resolved_nodes = set()
        for call in t["calls"]:
            resolved_nodes.update(_resolve_test_call(call, t["imports"], name_index,
                                                      class_index, class_methods, class_parent, mod_index))

        # Compute distances from resolved nodes to impact nodes (forward only)
        distances = _compute_distances(resolved_nodes, impact_ids, fwd)

        score = 0.0
        basis = []
        covers = []

        # Coupling 1: Direct (1.0) — test calls a node in the impact set
        direct_nodes = resolved_nodes & impact_ids
        if direct_nodes:
            score = max(score, 1.0)
            basis.append("direct_call")
            covers.extend(direct_nodes)
            covered.update(direct_nodes)

        # Coupling 2: Indirect (0.5/distance) — test calls a node at distance d from impact
        for nid, dist in distances.items():
            if dist > 0 and nid not in impact_ids:
                indirect_score = round(0.5 / dist, 3)
                if indirect_score > score:
                    score = indirect_score
                    basis.append(f"indirect_d{dist}")
                covers.append(nid)

        # Coupling 3: Name similarity (0.2) — test name contains an impact function name
        test_name_lower = t["test_name"].lower()
        for impact_name in impact_node_names:
            if len(impact_name) >= 3 and impact_name.lower() in test_name_lower:
                if 0.2 > score:
                    score = 0.2
                    basis.append("name_similarity")
                break

        if score > 0:
            risk = "high" if score >= 1.0 else ("medium" if score >= 0.5 else "low")
            selected.append({
                "test_file": t["test_file"], "test_name": t["test_name"],
                "node_id": list(covers)[:1] if covers else None,
                "coupling_score": round(score, 3),
                "coupling_basis": list(set(basis)),
                "covers": list(set(covers)),
                "risk_level": risk,
            })

    total = len(tests)
    sel = len(selected)
    cov = round(len(covered) / len(impact_ids), 3) if impact_ids else 0.0
    data = {
        "tests": selected,
        "metrics": {
            "total_tests": total, "selected": sel,
            "compression_ratio": round(sel / total, 3) if total else 0.0,
            "impact_coverage": cov,
        },
    }
    if not selected:
        return envelope(TOOL, STATUS_PARTIAL, data, [err("NO_SELECTED", "未选出任何测试")]), EXIT_PARTIAL
    return envelope(TOOL, STATUS_OK, data), EXIT_OK


def self_check():
    import tempfile
    g = {"nodes": [
        {"id": "a.py::f", "name": "f", "kind": "function", "file": "a.py", "line_range": [1, 2]},
        {"id": "a.py::g", "name": "g", "kind": "function", "file": "a.py", "line_range": [3, 4]},
        {"id": "a.py::h", "name": "h", "kind": "function", "file": "a.py", "line_range": [5, 6]},
    ], "edges": [
        {"from": "a.py::g", "to": "a.py::f", "type": "direct", "confidence": "exact", "site": {"file": "a.py", "line": 3}},
        {"from": "a.py::h", "to": "a.py::g", "type": "direct", "confidence": "exact", "site": {"file": "a.py", "line": 5}},
    ]}
    p = {"impact": [
        {"node_id": "a.py::f", "distance": 0, "path": ["a.py::f"], "fan_in": 1, "confidence": "exact", "truncated": False},
    ]}
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "test_f.py"), "w") as f:
            f.write("def test_f():\n    f()\n")
        with open(os.path.join(td, "test_h.py"), "w") as f:
            f.write("def test_h():\n    h()\n")  # h calls g calls f (distance 2)
        payload, code = run(p, g, td)
        assert payload["status"] == STATUS_OK
        assert payload["data"]["metrics"]["selected"] == 2
        # test_f should have score 1.0 (direct)
        tf = [t for t in payload["data"]["tests"] if t["test_name"] == "test_f"][0]
        assert tf["coupling_score"] == 1.0
        # test_h should have indirect score (0.5/2 = 0.25)
        th = [t for t in payload["data"]["tests"] if t["test_name"] == "test_h"][0]
        assert th["coupling_score"] == 0.25
    return envelope(TOOL, STATUS_OK, {"self_check": "pass"}), EXIT_OK


def main():
    ap = argparse.ArgumentParser(prog="testselect.py")
    ap.add_argument("--impact", required=False)
    ap.add_argument("--graph", required=False)
    ap.add_argument("--tests", required=False)
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()
    if args.self_check:
        payload, code = self_check()
        emit(payload)
        return code
    if not args.impact or not args.graph or not args.tests:
        emit(envelope(TOOL, STATUS_ERROR, {}, [err("MISSING_ARG", "--impact/--graph/--tests 必填")]))
        return EXIT_ERROR
    p = json.load(open(args.impact, "r", encoding="utf-8"))
    g = json.load(open(args.graph, "r", encoding="utf-8"))
    pd = p.get("data", p)
    gd = g.get("data", g)
    payload, code = run(pd, gd, args.tests)
    emit(payload)
    return code


if __name__ == "__main__":
    sys.exit(main())
