# -*- coding: utf-8 -*-
"""harness.py — ChangeRadar benchmark 四指标测量（纯标准库，零 pytest 依赖）。

四指标：
  1. 影响面召回率 (impact_recall)   — bugfix 代理真值：bugfix 修复的函数集 F 是否被 impact 覆盖
  2. 测试压缩率   (compression)     — 1 − selected / total
  3. 变异 kill 保持率 (kill_retention) — kill_rate(选中子集) / kill_rate(全量)
  4. 影响面收敛度 (convergence)     — impact 节点数 / 全图节点数

自定义 test loader：同时兼容 unittest.TestCase 子类与裸 test_* 函数，不依赖 pytest。
"""
import argparse
import ast
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import unittest
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO_ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

# 包内固定 demo 目录（唯一允许自动重建 git 历史的路径）
_DEMO_DIR = (Path(REPO_ROOT) / "fixtures" / "demo_repo").resolve()

from mutate import mutate_source, OPERATORS  # noqa: E402


# ---------------------------------------------------------------------------
# 自定义 test loader —— 纯标准库，兼容 TestCase + 裸 test_* 函数
# ---------------------------------------------------------------------------

def _load_plain_tests(module):
    """把模块里的裸 test_* 函数包成 unittest.FunctionTestCase。"""
    suite = unittest.TestSuite()
    for name in dir(module):
        if name.startswith("test_") and callable(getattr(module, name)):
            fn = getattr(module, name)
            suite.addTest(unittest.FunctionTestCase(fn))
    return suite


def discover_tests(tests_dir, top_dir):
    """发现 tests_dir 下所有 test_*.py，返回 unittest.TestSuite。

    兼容两种写法：unittest.TestCase 子类 + 裸 test_* 函数。
    top_dir 加入 sys.path 以保证 import 可达。
    """
    if top_dir not in sys.path:
        sys.path.insert(0, top_dir)
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for fname in sorted(os.listdir(tests_dir)):
        if not fname.startswith("test_") or not fname.endswith(".py"):
            continue
        modname = fname[:-3]
        # 强制重载（变异后的源文件已覆盖磁盘）
        if modname in sys.modules:
            del sys.modules[modname]
        # 同时清掉可能被缓存的业务模块
        for m in list(sys.modules):
            if m.split(".")[0] in ("models", "services", "utils", "app", "config"):
                del sys.modules[m]
        try:
            mod = importlib.import_module(modname)
        except Exception:
            # import 失败 → 该文件所有测试视为 error
            class _FailMod(unittest.TestCase):
                def runTest(self):
                    raise ImportError(f"failed to import {modname}: {traceback.format_exc()}")
            suite.addTest(_FailMod())
            continue
        # TestCase 子类
        for name in dir(mod):
            obj = getattr(mod, name)
            if isinstance(obj, type) and issubclass(obj, unittest.TestCase):
                suite.addTests(loader.loadTestsFromTestCase(obj))
        # 裸 test_* 函数
        suite.addTests(_load_plain_tests(mod))
    return suite


def run_tests(tests_dir, top_dir, selected_names=None):
    """运行测试，返回 (total, failures, errors, killed)。

    selected_names: 若给定，只运行 test_name 在该集合中的用例（变异 kill 子集测量）。
    """
    suite = discover_tests(tests_dir, top_dir)
    if selected_names is not None:
        filtered = unittest.TestSuite()
        for test in suite:
            tid = getattr(test, "_testMethodName", "") or getattr(test, "id", lambda: "")()
            # FunctionTestCase 的 id 形如 modname.test_func
            tid_str = test.id() if hasattr(test, "id") else ""
            name_part = tid_str.split(".")[-1]
            if name_part in selected_names:
                filtered.addTest(test)
        suite = filtered

    runner = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0)
    result = runner.run(suite)
    total = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    killed = failures + errors  # 任意 fail/error 都算 kill
    return total, failures, errors, killed


# ---------------------------------------------------------------------------
# 指标 1：影响面召回率（bugfix 代理真值）
# ---------------------------------------------------------------------------

def measure_impact_recall(repo_path, range_spec, bugfix_funcs):
    """bugfix 代理法：跑管线得到 impact，检查 bugfix 修复的函数集是否被覆盖。

    bugfix_funcs: list[str] — bugfix commit 修复的函数短名（代理 ground truth）。
    返回 (recall, impact_node_ids, covered, missed)。
    """
    import subprocess
    cg_json = os.path.join(tempfile.gettempdir(), "bench_cg.json")
    dp_json = os.path.join(tempfile.gettempdir(), "bench_dp.json")
    pp_json = os.path.join(tempfile.gettempdir(), "bench_pp.json")

    subprocess.run([sys.executable, os.path.join(SCRIPTS, "callgraph.py"),
                    "--root", repo_path], stderr=subprocess.DEVNULL,
                   stdout=open(cg_json, "w"))
    subprocess.run([sys.executable, os.path.join(SCRIPTS, "diffparse.py"),
                    "--range", range_spec, "--repo", repo_path,
                    "--graph", cg_json], stderr=subprocess.DEVNULL,
                   stdout=open(dp_json, "w"))
    subprocess.run([sys.executable, os.path.join(SCRIPTS, "propagate.py"),
                    "--graph", cg_json, "--changes", dp_json],
                   stderr=subprocess.DEVNULL, stdout=open(pp_json, "w"))

    with open(pp_json) as f:
        pp = json.load(f)
    impact_ids = [i["node_id"] for i in pp.get("data", {}).get("impact", [])]

    covered, missed = [], []
    for fn in bugfix_funcs:
        hit = any(fn in nid for nid in impact_ids)
        (covered if hit else missed).append(fn)
    recall = len(covered) / len(bugfix_funcs) if bugfix_funcs else 0.0
    return recall, impact_ids, covered, missed


# ---------------------------------------------------------------------------
# 指标 2 & 4：测试压缩率 + 影响面收敛度
# ---------------------------------------------------------------------------

def measure_compression_and_convergence(repo_path, range_spec):
    import subprocess
    cg_json = os.path.join(tempfile.gettempdir(), "bench_cg.json")
    dp_json = os.path.join(tempfile.gettempdir(), "bench_dp.json")
    pp_json = os.path.join(tempfile.gettempdir(), "bench_pp.json")
    ts_json = os.path.join(tempfile.gettempdir(), "bench_ts.json")

    if not os.path.exists(cg_json):
        subprocess.run([sys.executable, os.path.join(SCRIPTS, "callgraph.py"),
                        "--root", repo_path], stderr=subprocess.DEVNULL,
                       stdout=open(cg_json, "w"))
    if not os.path.exists(dp_json):
        subprocess.run([sys.executable, os.path.join(SCRIPTS, "diffparse.py"),
                        "--range", range_spec, "--repo", repo_path,
                        "--graph", cg_json], stderr=subprocess.DEVNULL,
                       stdout=open(dp_json, "w"))
    if not os.path.exists(pp_json):
        subprocess.run([sys.executable, os.path.join(SCRIPTS, "propagate.py"),
                        "--graph", cg_json, "--changes", dp_json],
                       stderr=subprocess.DEVNULL, stdout=open(pp_json, "w"))

    with open(cg_json) as f:
        cg = json.load(f)
    with open(pp_json) as f:
        pp = json.load(f)

    total_nodes = len(cg.get("data", {}).get("nodes", []))
    impact_nodes = len(pp.get("data", {}).get("impact", []))
    convergence = impact_nodes / total_nodes if total_nodes else 0.0

    tests_dir = os.path.join(repo_path, "tests")
    subprocess.run([sys.executable, os.path.join(SCRIPTS, "testselect.py"),
                    "--impact", pp_json, "--graph", cg_json, "--tests", tests_dir],
                   stderr=subprocess.DEVNULL, stdout=open(ts_json, "w"))
    with open(ts_json) as f:
        ts = json.load(f)
    m = ts.get("data", {}).get("metrics", {})
    total_tests = m.get("total_tests", 0)
    selected = m.get("selected", 0)
    compression = 1 - (selected / total_tests) if total_tests else 0.0
    selected_names = {t["test_name"] for t in ts.get("data", {}).get("tests", []) if t.get("coupling_score", 0) > 0}

    return compression, convergence, total_tests, selected, selected_names, impact_nodes, total_nodes


# ---------------------------------------------------------------------------
# 指标 3：变异 kill 保持率
# ---------------------------------------------------------------------------

def measure_kill_retention(repo_path, tests_dir, target_funcs, selected_names):
    """对 target_funcs 逐个注入变异，分别跑全量与选中子集，算 kill 保持率。

    target_funcs: list of (file_relpath, func_name) — 限变异范围在 impact 覆盖的函数。
    返回 (retention, kill_full, kill_selected, details)。
    """
    killed_full = 0
    killed_selected = 0
    total_mutants = 0
    details = []

    for relpath, func_name in target_funcs:
        src_path = os.path.join(repo_path, relpath)
        if not os.path.exists(src_path):
            continue
        original_src = open(src_path, encoding="utf-8").read()
        for op in OPERATORS:
            result = mutate_source(original_src, op, func_name)
            if result is None:
                continue
            mutated_src, desc = result
            total_mutants += 1
            # 写入变异版本
            with open(src_path, "w", encoding="utf-8") as f:
                f.write(mutated_src)
            try:
                # 全量
                _, _, _, k_full = run_tests(tests_dir, repo_path)
                # 选中子集
                _, _, _, k_sel = run_tests(tests_dir, repo_path, selected_names)
            finally:
                # 恢复原始源文件
                with open(src_path, "w", encoding="utf-8") as f:
                    f.write(original_src)
            # 清模块缓存
            for m in list(sys.modules):
                if m.split(".")[0] in ("models", "services", "utils", "app", "config") or m.startswith("test_"):
                    del sys.modules[m]

            full_killed = k_full > 0
            sel_killed = k_sel > 0
            if full_killed:
                killed_full += 1
            if sel_killed:
                killed_selected += 1
            details.append({
                "file": relpath, "func": func_name, "operator": op, "desc": desc,
                "killed_by_full": full_killed, "killed_by_selected": sel_killed,
            })

    kill_rate_full = killed_full / total_mutants if total_mutants else 0.0
    kill_rate_sel = killed_selected / total_mutants if total_mutants else 0.0
    retention = kill_rate_sel / kill_rate_full if kill_rate_full > 0 else 1.0
    return retention, kill_rate_full, kill_rate_sel, total_mutants, details


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def _ensure_git_history(repo_path):
    """确保 repo_path 下有 .git；缺则按合规策略处理。

    v5 合规策略：绝不自动执行用户仓库路径下的任意 shell 脚本。
    仅当 repo_path 解析后严格等于包内固定 demo 目录 (fixtures/demo_repo)
    时，才允许自动调 rebuild_history.sh 重建；其余路径缺 .git → 打印手动
    初始化指引并跳过自动重建。
    """
    git_dir = os.path.join(repo_path, ".git")
    if os.path.isdir(git_dir):
        return
    try:
        resolved = Path(repo_path).resolve()
    except Exception:
        resolved = None
    if resolved != _DEMO_DIR:
        print("[harness] 目标仓库缺 .git。为合规起见，本工具不会自动执行仓库内脚本。")
        print("[harness] 请手动初始化 git 历史后重试：cd {0} && bash rebuild_history.sh".format(repo_path))
        return
    rebuild = os.path.join(repo_path, "rebuild_history.sh")
    if os.path.isfile(rebuild):
        print("[harness] .git missing, running rebuild_history.sh ...")
        subprocess.run(["bash", "rebuild_history.sh"], capture_output=True,
                       text=True, timeout=30, cwd=os.path.abspath(repo_path))


def run_benchmark(repo_path, range_spec, bugfix_funcs, target_funcs):
    """跑完整四指标，返回 dict。"""
    _ensure_git_history(repo_path)
    print(f"[harness] repo={repo_path} range={range_spec}")
    print(f"[harness] bugfix proxy funcs={bugfix_funcs}")
    print(f"[harness] mutation targets={target_funcs}")

    # 指标 1：影响面召回率
    recall, impact_ids, covered, missed = measure_impact_recall(repo_path, range_spec, bugfix_funcs)
    print(f"[harness] ① impact_recall = {recall:.1%}  covered={covered} missed={missed}")

    # 指标 2 & 4
    compression, convergence, total_tests, selected, selected_names, impact_nodes, total_nodes = \
        measure_compression_and_convergence(repo_path, range_spec)
    print(f"[harness] ② compression = {compression:.1%}  ({selected}/{total_tests} selected)")
    print(f"[harness] ④ convergence = {convergence:.1%}  ({impact_nodes}/{total_nodes} nodes)")

    # 指标 3：变异 kill 保持率
    tests_dir = os.path.join(repo_path, "tests")
    retention, kr_full, kr_sel, n_mut, details = measure_kill_retention(
        repo_path, tests_dir, target_funcs, selected_names)
    print(f"[harness] ③ kill_retention = {retention:.1%}  "
          f"(full={kr_full:.1%} sel={kr_sel:.1%} mutants={n_mut})")

    return {
        "impact_recall": round(recall, 4),
        "compression": round(compression, 4),
        "kill_retention": round(retention, 4),
        "convergence": round(convergence, 4),
        "detail": {
            "total_tests": total_tests,
            "selected": selected,
            "impact_nodes": impact_nodes,
            "total_nodes": total_nodes,
            "covered_funcs": covered,
            "missed_funcs": missed,
            "mutants_total": n_mut,
            "kill_rate_full": round(kr_full, 4),
            "kill_rate_selected": round(kr_sel, 4),
            "selected_test_names": sorted(selected_names),
            "mutation_details": details,
        },
    }


def main():
    ap = argparse.ArgumentParser(prog="harness.py")
    ap.add_argument("--repo", required=True, help="fixture repo path")
    ap.add_argument("--range", required=True, help="commit range A..B")
    ap.add_argument("--bugfix-funcs", required=True, help="comma-separated bugfix func names (proxy ground truth)")
    ap.add_argument("--mutate-funcs", required=True,
                    help="comma-separated file:func pairs to mutate (e.g. models/order.py:total)")
    ap.add_argument("--output", default=None, help="output JSON path")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    bugfix_funcs = [f.strip() for f in args.bugfix_funcs.split(",") if f.strip()]
    target_funcs = []
    for pair in args.mutate_funcs.split(","):
        pair = pair.strip()
        if ":" in pair:
            fpath, fname = pair.rsplit(":", 1)
            target_funcs.append((fpath, fname))

    result = run_benchmark(repo, args.range, bugfix_funcs, target_funcs)
    out = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        open(args.output, "w", encoding="utf-8").write(out)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
