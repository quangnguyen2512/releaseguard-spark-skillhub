# -*- coding: utf-8 -*-
"""mutate.py — 纯标准库 AST 变异算子（5 种），为 benchmark harness 提供变异注入。

5 个算子：
  1. flip_compare  — 比较运算符取反（== ↔ !=, < ↔ >=, > ↔ <=, <= ↔ >, >= ↔ <）
  2. mutate_return — return 表达式取反（bool）或置 None
  3. drop_call     — 表达式语句中的函数调用替换为 pass
  4. mutate_const  — 数值常量 ±1、字符串置空、布尔取反
  5. negate_if     — if 条件取反

每个算子对单个 AST 节点做一次变异（first-hit），返回 (mutated_source, description) 或 None（无可变异点）。
全部基于 ast 标准库，零第三方依赖。
"""
import ast
import copy

OPERATORS = ["flip_compare", "mutate_return", "drop_call", "mutate_const", "negate_if"]

_COMPARE_FLIP = {
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
    ast.Lt: ast.GtE, ast.GtE: ast.Lt,
    ast.Gt: ast.LtE, ast.LtE: ast.Gt,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
}


def _apply_mutation(tree, mutator_fn):
    """对 tree 做首次命中变异，返回 (mutated_tree, desc) 或 None。"""
    result = {"hit": False, "desc": None}

    class _Mutator(ast.NodeTransformer):
        def visit(self, node):
            if result["hit"]:
                return node  # already mutated, skip
            return super().visit(node)

        def generic_visit(self, node):
            if result["hit"]:
                return node
            desc = mutator_fn(node)
            if desc is not None:
                result["hit"] = True
                result["desc"] = desc
                return node  # node already mutated in-place by mutator_fn
            return super().generic_visit(node)

    _Mutator().visit(tree)
    if result["hit"]:
        ast.fix_missing_locations(tree)
        return tree, result["desc"]
    return None


def _flip_compare(node):
    if isinstance(node, ast.Compare):
        for op in node.ops:
            new_cls = _COMPARE_FLIP.get(type(op))
            if new_cls:
                idx = node.ops.index(op)
                node.ops[idx] = new_cls()
                return f"flip {type(op).__name__}->{new_cls.__name__} @line{node.lineno}"
    return None


def _mutate_return(node):
    if isinstance(node, ast.Return) and node.value is not None:
        v = node.value
        # bool constant → negate
        if isinstance(v, ast.Constant) and isinstance(v.value, bool):
            v.value = not v.value
            return f"return bool negate @line{node.lineno}"
        # UnaryOp Not → unwrap
        if isinstance(v, ast.UnaryOp) and isinstance(v.op, ast.Not):
            node.value = v.operand
            return f"return not->val @line{node.lineno}"
        # Wrap with not (best-effort, may change type but that's the point — kill test)
        node.value = ast.UnaryOp(op=ast.Not(), operand=v)
        return f"return val->not @line{node.lineno}"
    return None


def _drop_call(node):
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        lineno = node.lineno
        node.value = ast.Constant(value=None)
        return f"drop call @line{lineno}"
    return None


def _mutate_const(node):
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):
            return None  # handled by mutate_return / dedicated
        if isinstance(v, int):
            node.value = v + 1
            return f"const int {v}->{v+1} @line{node.lineno}"
        if isinstance(v, float):
            node.value = v + 1.0
            return f"const float {v}->{v+1.0} @line{node.lineno}"
        if isinstance(v, str):
            node.value = ""
            return f'const str->"" @line{node.lineno}'
    return None


def _negate_if(node):
    if isinstance(node, ast.If):
        node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)
        return f"negate if @line{node.lineno}"
    return None


_MUTATORS = {
    "flip_compare": _flip_compare,
    "mutate_return": _mutate_return,
    "drop_call": _drop_call,
    "mutate_const": _mutate_const,
    "negate_if": _negate_if,
}


def mutate_source(source_code, operator, func_name=None):
    """对 source_code 应用指定算子。

    func_name: 若指定，只在该函数/方法体内做变异（限定变异范围）。
    返回 (mutated_source, description) 或 None（无可变异点）。
    保留完整源码（含 import / 模块级代码），只在目标函数作用域内变异。
    """
    tree = ast.parse(source_code)
    mutator = _MUTATORS.get(operator)
    if not mutator:
        raise ValueError(f"unknown operator: {operator}; valid: {OPERATORS}")

    # 收集目标函数体内的所有节点的行号区间，用于限定变异范围
    target_ranges = []
    if func_name:
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == func_name:
                target_ranges.append((stmt.lineno, stmt.end_lineno))
            elif isinstance(stmt, ast.ClassDef):
                for cls_stmt in stmt.body:
                    if isinstance(cls_stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and cls_stmt.name == func_name:
                        target_ranges.append((cls_stmt.lineno, cls_stmt.end_lineno))
        if not target_ranges:
            return None
    else:
        target_ranges = None  # 不限定，全树可变异

    def _in_target(node):
        if target_ranges is None:
            return True
        ln = getattr(node, "lineno", -1)
        for lo, hi in target_ranges:
            if lo <= ln <= hi:
                return True
        return False

    result = {"hit": False, "desc": None}

    class _Mutator(ast.NodeTransformer):
        def visit(self, node):
            if result["hit"]:
                return node
            return super().visit(node)

        def generic_visit(self, node):
            if result["hit"]:
                return node
            # 只在目标函数作用域内的节点尝试变异
            if _in_target(node):
                desc = mutator(node)
                if desc is not None:
                    result["hit"] = True
                    result["desc"] = desc
                    return node
            return super().generic_visit(node)

    _Mutator().visit(tree)
    if result["hit"]:
        ast.fix_missing_locations(tree)
        return ast.unparse(tree), result["desc"]
    return None


def list_mutations(source_code, func_name=None):
    """列出指定函数上每个算子是否可变异 + 描述（不实际改写），供 harness 枚举。"""
    out = []
    for op in OPERATORS:
        r = mutate_source(source_code, op, func_name)
        out.append({"operator": op, "applicable": r is not None, "desc": r[1] if r else None})
    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: mutate.py <source.py> [func_name]")
        sys.exit(1)
    src = open(sys.argv[1], encoding="utf-8").read()
    fn = sys.argv[2] if len(sys.argv) > 2 else None
    for m in list_mutations(src, fn):
        print(f"  {m['operator']:14s} applicable={m['applicable']}  {m['desc'] or ''}")
