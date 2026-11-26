# -*- coding: utf-8 -*-
"""callgraph.py — AST 符号表 + 调用图构建（Day2 完整实现）。

两阶段 AST 遍历 + 跨文件 import 解析 + 单继承 MRO + virtual 保守边
+ unknown-dispatch 五条标记规则 + dynamic 模块标记。

输入：--root <path>
输出 data：{root, stats, nodes[], edges[]}
  nodes: {id,name,kind,file,line_range,confidence,external?,dynamic?,decorators?,bases?,class?,unknown_dispatch?}
  edges: {from,to,type,confidence,site:{file,line}}
  type: direct|cross_file|virtual|super|constructor|unknown_dispatch
  confidence: exact|conservative|unknown
退出码：0=完整图 / 1=部分文件解析失败但图可用 / 2=全失败
"""
import argparse, ast, os, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _envelope import envelope, emit, STATUS_OK, STATUS_PARTIAL, STATUS_ERROR, EXIT_OK, EXIT_PARTIAL, EXIT_ERROR, err

TOOL = "callgraph"

_BUILTIN_DECORATORS = {"staticmethod", "classmethod", "property", "abstractmethod"}


def _node_id(relpath, parts):
    return "::".join([relpath] + parts)


def _split_node_id(nid):
    """Split node_id into (relpath, parts_list)."""
    idx = nid.index("::")
    rel = nid[:idx]
    rest = nid[idx + 2:]
    parts = rest.split("::") if rest != "<module>" else ["<module>"]
    return rel, parts


def _has_user_decorator(decorator_list):
    """True if any decorator is not a builtin (staticmethod/classmethod/property)."""
    for d in decorator_list:
        name = None
        if isinstance(d, ast.Name):
            name = d.id
        elif isinstance(d, ast.Attribute):
            name = d.attr
        if name not in _BUILTIN_DECORATORS:
            return True
    return False


def build(root):
    """两阶段 AST 遍历。返回 (data, parse_failures)。"""
    nodes, edges = [], []
    parse_failures = []
    edge_set = set()  # dedup: (from, to, type)

    # ---- Pass 0: collect py_files + module index ----
    py_files = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__" and d != ".git"]
        for fn in files:
            if fn.endswith(".py"):
                py_files.append(os.path.join(dirpath, fn))

    mod_index = {}  # dotted module path → relpath
    for ap in py_files:
        rel = os.path.relpath(ap, root).replace(os.sep, "/")
        mod = rel[:-3].replace("/", ".")
        if mod.endswith(".__init__"):
            mod = mod[:-9]
        mod_index[mod] = rel

    # ---- Storage ----
    file_data = {}  # rel → {tree, src_lines, imports, is_dynamic}
    class_index = defaultdict(list)  # class_name → [(relpath, node_id)]
    class_bases = {}  # node_id → [base_class_name_strings]
    class_methods = {}  # node_id → {method_name: method_node_id}
    local_syms = {}  # (relpath, name) → node_id

    # ---- Pass 1: Parse all files, collect symbols ----
    for ap in py_files:
        rel = os.path.relpath(ap, root).replace(os.sep, "/")
        try:
            src = open(ap, "r", encoding="utf-8").read()
            tree = ast.parse(src, filename=ap)
        except Exception as e:
            parse_failures.append(err("PARSE_FAIL", str(e), rel))
            continue

        src_lines = src.splitlines()
        is_dynamic = False
        imports = {}  # local_name → {"type": ..., "module": ..., "symbol": ...}

        # Parse imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    imports[name] = {"type": "module", "module": alias.name}
            elif isinstance(node, ast.ImportFrom):
                if node.names[0].name == "*":
                    is_dynamic = True
                else:
                    src_mod = node.module or ""
                    for alias in node.names:
                        name = alias.asname or alias.name
                        imports[name] = {"type": "symbol", "module": src_mod, "symbol": alias.name}

        # Detect test files: in tests/ or test/ dir, or filename starts with test_ / ends with _test.py
        rel_dir = os.path.dirname(rel)
        is_test = (rel_dir.startswith("test") or
                   os.path.basename(rel).startswith("test_") or
                   os.path.basename(rel).endswith("_test.py"))

        file_data[rel] = {"tree": tree, "src_lines": src_lines, "imports": imports,
                          "is_dynamic": is_dynamic, "is_test": is_test}

        # Module node
        mod_id = _node_id(rel, ["<module>"])
        nodes.append({
            "id": mod_id, "name": rel, "kind": "module",
            "file": rel, "line_range": [1, len(src_lines) or 1],
            "confidence": "exact", "dynamic": is_dynamic or None,
            "is_test": is_test or None,
        })

        # Collect top-level classes and functions
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nid = _node_id(rel, [node.name])
                decs = [ast.unparse(d) for d in node.decorator_list] if node.decorator_list else None
                has_ud = _has_user_decorator(node.decorator_list)
                nodes.append({
                    "id": nid, "name": node.name, "kind": "function",
                    "file": rel, "line_range": [node.lineno, getattr(node, "end_lineno", node.lineno)],
                    "confidence": "exact", "dynamic": is_dynamic or None,
                    "decorators": decs, "unknown_dispatch": has_ud or None,
                    "is_test": is_test or None,
                })
                local_syms[(rel, node.name)] = nid
            elif isinstance(node, ast.ClassDef):
                nid = _node_id(rel, [node.name])
                bases = []
                for b in node.bases:
                    if isinstance(b, ast.Name):
                        bases.append(b.id)
                    elif isinstance(b, ast.Attribute):
                        try:
                            bases.append(ast.unparse(b))
                        except Exception:
                            bases.append("?")
                decs = [ast.unparse(d) for d in node.decorator_list] if node.decorator_list else None
                nodes.append({
                    "id": nid, "name": node.name, "kind": "class",
                    "file": rel, "line_range": [node.lineno, getattr(node, "end_lineno", node.lineno)],
                    "confidence": "exact", "dynamic": is_dynamic or None,
                    "decorators": decs, "bases": bases or None,
                    "is_test": is_test or None,
                })
                class_index[node.name].append((rel, nid))
                class_bases[nid] = bases
                class_methods[nid] = {}
                local_syms[(rel, node.name)] = nid
                # Collect methods
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        m_nid = _node_id(rel, [node.name, item.name])
                        m_decs = [ast.unparse(d) for d in item.decorator_list] if item.decorator_list else None
                        has_ud = _has_user_decorator(item.decorator_list)
                        # Detect getattr / string dispatch inside method body
                        for sub in ast.walk(item):
                            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "getattr":
                                has_ud = True
                                break
                        nodes.append({
                            "id": m_nid, "name": item.name, "kind": "method",
                            "file": rel, "line_range": [item.lineno, getattr(item, "end_lineno", item.lineno)],
                            "confidence": "exact", "dynamic": is_dynamic or None,
                            "decorators": m_decs, "unknown_dispatch": has_ud or None,
                            "class": nid, "is_test": is_test or None,
                        })
                        class_methods[nid][item.name] = m_nid
                        local_syms[(rel, item.name)] = m_nid

    files_scanned = len(file_data)

    # ---- Build subclass index ----
    subclass_index = defaultdict(list)  # base_node_id → [subclass_node_ids]

    def resolve_class_name(name, rel, imports):
        """Resolve a class name to its node_id (local → import → global fallback)."""
        local = local_syms.get((rel, name))
        if local and local in class_methods:
            return local
        if name in imports:
            imp = imports[name]
            if imp["type"] == "symbol":
                src_rel = mod_index.get(imp["module"])
                if src_rel:
                    tid = local_syms.get((src_rel, imp["symbol"]))
                    if tid and tid in class_methods:
                        return tid
        candidates = class_index.get(name, [])
        if len(candidates) == 1:
            return candidates[0][1]
        # Try to find by import module
        if name in imports:
            imp = imports[name]
            if imp["type"] == "symbol":
                src_rel = mod_index.get(imp["module"])
                if src_rel:
                    for (crel, cnid) in class_index.get(name, []):
                        if crel == src_rel:
                            return cnid
        return None

    for cls_nid, bases in class_bases.items():
        rel, _ = _split_node_id(cls_nid)
        fd = file_data.get(rel, {})
        imports = fd.get("imports", {})
        for bname in bases:
            base_nid = resolve_class_name(bname, rel, imports)
            if base_nid and base_nid != cls_nid:
                subclass_index[base_nid].append(cls_nid)

    # ---- Instance type tracking ----
    # (rel, enclosing_class_nid, attr) → class_name
    instance_types = {}
    for rel, fd in file_data.items():
        tree = fd["tree"]
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                cls_nid = _node_id(rel, [node.name])
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for sub in ast.walk(item):
                            if (isinstance(sub, ast.Assign) and len(sub.targets) == 1
                                    and isinstance(sub.targets[0], ast.Attribute)
                                    and isinstance(sub.targets[0].value, ast.Name)
                                    and sub.targets[0].value.id == "self"
                                    and isinstance(sub.value, ast.Call)
                                    and isinstance(sub.value.func, ast.Name)):
                                instance_types[(rel, cls_nid, sub.targets[0].attr)] = sub.value.func.id

    # ---- MRO resolution helpers ----
    def resolve_method_mro(cls_nid, method_name):
        """Return (method_node_id or None, is_inherited) along single-inheritance MRO."""
        visited = set()
        cur = cls_nid
        while cur and cur not in visited:
            visited.add(cur)
            methods = class_methods.get(cur, {})
            if method_name in methods:
                return methods[method_name], (cur != cls_nid)
            # Find base
            bases = class_bases.get(cur, [])
            rel_cur, _ = _split_node_id(cur)
            fd = file_data.get(rel_cur, {})
            next_base = None
            for bname in bases:
                next_base = resolve_class_name(bname, rel_cur, fd.get("imports", {}))
                if next_base:
                    break
            cur = next_base
        return None, False

    def get_all_subclass_overrides(cls_nid, method_name):
        """Find all subclass overrides of method_name (recursive)."""
        result = []
        for sub_nid in subclass_index.get(cls_nid, []):
            methods = class_methods.get(sub_nid, {})
            if method_name in methods:
                result.append(methods[method_name])
            result.extend(get_all_subclass_overrides(sub_nid, method_name))
        return result

    def add_edge(from_id, to_id, etype, confidence, rel, line):
        key = (from_id, to_id, etype)
        if key in edge_set:
            return
        edge_set.add(key)
        edges.append({
            "from": from_id, "to": to_id, "type": etype,
            "confidence": confidence, "site": {"file": rel, "line": line},
        })

    # ---- Pass 2: Edge building ----
    for rel, fd in file_data.items():
        tree = fd["tree"]
        imports = fd["imports"]
        is_dynamic = fd["is_dynamic"]

        def process_func(func_node, caller_id, enclosing_class):
            """Walk function body for Call nodes and build edges."""
            for call in ast.walk(func_node):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                line = call.lineno

                # --- Case 1: Name(id) — direct function call ---
                if isinstance(func, ast.Name):
                    callee_name = func.id

                    # getattr → unknown_dispatch (mark caller)
                    if callee_name == "getattr":
                        # Already detected in Pass 1 for methods; mark for functions
                        continue

                    # Constructor call: name resolves to a class
                    cls_nid = resolve_class_name(callee_name, rel, imports)
                    if cls_nid and callee_name not in ("print", "str", "int", "float", "list",
                                                        "dict", "set", "tuple", "len", "range",
                                                        "sum", "min", "max", "abs", "round",
                                                        "sorted", "reversed", "enumerate", "zip",
                                                        "isinstance", "issubclass", "type", "super",
                                                        "open", "bool", "bytes", "format", "input"):
                        # Constructor → __init__
                        init_nid, inherited = resolve_method_mro(cls_nid, "__init__")
                        if init_nid and init_nid != caller_id:
                            conf = "conservative" if is_dynamic else "exact"
                            add_edge(caller_id, init_nid, "constructor", conf, rel, line)
                        continue

                    # Local symbol
                    tid = local_syms.get((rel, callee_name))
                    if tid and tid != caller_id:
                        conf = "conservative" if is_dynamic else "exact"
                        add_edge(caller_id, tid, "direct", conf, rel, line)
                        continue

                    # Imported symbol (from x import f)
                    if callee_name in imports:
                        imp = imports[callee_name]
                        if imp["type"] == "symbol":
                            src_rel = mod_index.get(imp["module"])
                            if src_rel:
                                tid = local_syms.get((src_rel, imp["symbol"]))
                                if tid and tid != caller_id:
                                    conf = "conservative" if is_dynamic else "exact"
                                    add_edge(caller_id, tid, "cross_file", conf, rel, line)

                # --- Case 2: Attribute(value, attr) ---
                elif isinstance(func, ast.Attribute):
                    attr_name = func.attr
                    value = func.value

                    # 2a: self.method() — virtual dispatch
                    if isinstance(value, ast.Name) and value.id == "self":
                        if enclosing_class:
                            m_nid, inherited = resolve_method_mro(enclosing_class, attr_name)
                            if m_nid and m_nid != caller_id:
                                conf = "conservative" if (inherited or is_dynamic) else "exact"
                                add_edge(caller_id, m_nid, "virtual", conf, rel, line)
                            # Virtual conservative: subclass overrides
                            for sub_m_nid in get_all_subclass_overrides(enclosing_class, attr_name):
                                if sub_m_nid != caller_id and sub_m_nid != m_nid:
                                    add_edge(caller_id, sub_m_nid, "virtual", "conservative", rel, line)

                    # 2b: super().method()
                    elif (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                          and value.func.id == "super"):
                        if enclosing_class:
                            bases = class_bases.get(enclosing_class, [])
                            for bname in bases:
                                base_nid = resolve_class_name(bname, rel, imports)
                                if base_nid:
                                    m_nid, _ = resolve_method_mro(base_nid, attr_name)
                                    if m_nid and m_nid != caller_id:
                                        add_edge(caller_id, m_nid, "super", "exact", rel, line)
                                    break

                    # 2c: imported_module.function()
                    elif isinstance(value, ast.Name) and value.id in imports:
                        imp = imports[value.id]
                        if imp["type"] == "module":
                            src_mod = imp["module"]
                            src_rel = mod_index.get(src_mod)
                            if src_rel:
                                tid = local_syms.get((src_rel, attr_name))
                                if tid and tid != caller_id:
                                    conf = "conservative" if is_dynamic else "exact"
                                    add_edge(caller_id, tid, "cross_file", conf, rel, line)

                    # 2d: self.attr.method() — tracked instance type
                    elif (isinstance(value, ast.Attribute)
                          and isinstance(value.value, ast.Name)
                          and value.value.id == "self"):
                        attr_chain = value.attr
                        if enclosing_class:
                            cls_name = instance_types.get((rel, enclosing_class, attr_chain))
                            if cls_name:
                                inst_nid = resolve_class_name(cls_name, rel, imports)
                                if inst_nid:
                                    m_nid, inherited = resolve_method_mro(inst_nid, attr_name)
                                    if m_nid and m_nid != caller_id:
                                        conf = "conservative" if is_dynamic else "exact"
                                        add_edge(caller_id, m_nid, "cross_file", conf, rel, line)
                                    # Virtual: subclass overrides of this method
                                    for sub_m_nid in get_all_subclass_overrides(inst_nid, attr_name):
                                        if sub_m_nid != caller_id and sub_m_nid != m_nid:
                                            add_edge(caller_id, sub_m_nid, "virtual", "conservative", rel, line)

                    # 2e: local_var.method() — tracked local instance
                    elif isinstance(value, ast.Name):
                        var_name = value.id
                        # Check if this variable was assigned from a constructor call
                        # in the same function scope
                        cls_name = _find_local_instance_type(func_node, var_name, rel, imports)
                        if cls_name:
                            inst_nid = resolve_class_name(cls_name, rel, imports)
                            if inst_nid:
                                m_nid, _ = resolve_method_mro(inst_nid, attr_name)
                                if m_nid and m_nid != caller_id:
                                    conf = "conservative" if is_dynamic else "exact"
                                    add_edge(caller_id, m_nid, "cross_file", conf, rel, line)

        # Process top-level functions and class methods
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                caller_id = _node_id(rel, [node.name])
                process_func(node, caller_id, None)
            elif isinstance(node, ast.ClassDef):
                cls_nid = _node_id(rel, [node.name])
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        caller_id = _node_id(rel, [node.name, item.name])
                        process_func(item, caller_id, cls_nid)

    data = {
        "root": os.path.relpath(root),
        "stats": {
            "files": files_scanned,
            "nodes": len(nodes),
            "edges": len(edges),
            "parse_failures": len(parse_failures),
            "classes": len(class_methods),
            "dynamic_modules": sum(1 for fd in file_data.values() if fd["is_dynamic"]),
        },
        "nodes": nodes,
        "edges": edges,
    }
    return data, parse_failures


def _find_local_instance_type(func_node, var_name, rel, imports):
    """Find the class name for a local variable assigned from ClassName() in the function scope."""
    for node in ast.walk(func_node):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == var_name
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)):
            return node.value.func.id
    return None


def run(root, cache=None):
    data, pf = build(root)
    if pf and not data["nodes"]:
        return envelope(TOOL, STATUS_ERROR, {}, pf), EXIT_ERROR
    status = STATUS_PARTIAL if pf else STATUS_OK
    return envelope(TOOL, status, data, pf), (EXIT_PARTIAL if pf else EXIT_OK)


def self_check():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        # Create a mini project with cross-file call, inheritance, and virtual dispatch
        os.makedirs(os.path.join(td, "models"), exist_ok=True)
        with open(os.path.join(td, "models", "__init__.py"), "w") as f:
            f.write("")
        with open(os.path.join(td, "models", "base.py"), "w") as f:
            f.write("class BaseModel:\n    def save(self, data):\n        self.validate(data)\n        return data\n    def validate(self, data):\n        return True\n")
        with open(os.path.join(td, "models", "order.py"), "w") as f:
            f.write("from models.base import BaseModel\nclass OrderModel(BaseModel):\n    def validate(self, data):\n        super().validate(data)\n        return True\n    def total(self, items):\n        return sum(i for i in items)\n")
        with open(os.path.join(td, "svc.py"), "w") as f:
            f.write("from models.order import OrderModel\nclass Service:\n    def __init__(self):\n        self.obj = OrderModel()\n    def run(self, items):\n        self.obj.total(items)\n        self.obj.save(items)\n        self.obj.validate(items)\n")
        payload, code = run(td)
        assert payload["status"] in (STATUS_OK, STATUS_PARTIAL)
        impact_ids = [n["id"] for n in payload["data"]["nodes"]]
        # Check cross-file edges exist
        edge_tos = [e["to"] for e in payload["data"]["edges"]]
        assert any("OrderModel::total" in t for t in edge_tos), f"Missing edge to OrderModel.total, edges: {edge_tos}"
        assert any("BaseModel::save" in t for t in edge_tos), f"Missing edge to BaseModel.save"
        # Check virtual edge: BaseModel.save → OrderModel.validate (override)
        virtual_edges = [e for e in payload["data"]["edges"] if e["type"] == "virtual"]
        assert any("OrderModel::validate" in e["to"] for e in virtual_edges), "Missing virtual edge to OrderModel.validate"
        # Check cross_file edge from Service.run
        svc_edges = [e for e in payload["data"]["edges"] if "svc.py" in e["from"]]
        assert any("OrderModel::total" in e["to"] for e in svc_edges), "Missing cross_file edge to OrderModel.total"
    return envelope(TOOL, STATUS_OK, {"self_check": "pass"}), EXIT_OK


def main():
    ap = argparse.ArgumentParser(prog="callgraph.py")
    ap.add_argument("--root", help="项目根路径")
    ap.add_argument("--cache", help="缓存调用图 JSON 路径（增量合并）")
    ap.add_argument("--self-check", action="store_true", help="自检模式")
    args = ap.parse_args()
    if args.self_check:
        payload, code = self_check()
        emit(payload)
        return code
    if not args.root:
        emit(envelope(TOOL, STATUS_ERROR, {}, [err("MISSING_ARG", "--root 必填")]))
        return EXIT_ERROR
    payload, code = run(args.root, args.cache)
    emit(payload)
    return code


if __name__ == "__main__":
    sys.exit(main())
