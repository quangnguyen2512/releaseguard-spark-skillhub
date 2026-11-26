# -*- coding: utf-8 -*-
"""cache.py — 文件哈希增量缓存。

输入：--root <path> --cache-dir <dir>
输出（data）：{cached, root_hash, changed_files, added_files, deleted_files, rebuild_scope}
退出码：0=有缓存决策 / 2=缓存不可用→全量
rebuild_scope: full|incremental|none
"""
import argparse, hashlib, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _envelope import envelope, emit, STATUS_OK, STATUS_ERROR, STATUS_PARTIAL, EXIT_OK, EXIT_ERROR, err

TOOL = "cache"


def _hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _scan(root):
    """扫描 .py 文件，返回 {relpath: sha256}。"""
    manifest = {}
    for dirpath, _dirs, files in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for fn in files:
            if fn.endswith(".py"):
                ap = os.path.join(dirpath, fn)
                rel = os.path.relpath(ap, root)
                manifest[rel.replace(os.sep, "/")] = _hash_file(ap)
    return manifest


def run(root, cache_dir):
    cur = _scan(root)
    cache_file = os.path.join(cache_dir, "manifest.json")
    root_hash = hashlib.sha256(json.dumps(sorted(cur.items()), ensure_ascii=False).encode()).hexdigest()
    prev = None
    cached = os.path.exists(cache_file)
    if cached:
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                prev = json.load(f)
            if prev.get("schema_version") != "1.0":
                prev = None
        except Exception:
            prev = None
    if prev is None:
        changed, added, deleted = [], [], list(cur.keys())
        scope = "full"
        # 首次写入缓存
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({"schema_version": "1.0", "root_hash": root_hash, "files": cur}, f, ensure_ascii=False)
    else:
        old = prev.get("files", {})
        changed = [k for k in cur if k in old and cur[k] != old[k]]
        added = [k for k in cur if k not in old]
        deleted = [k for k in old if k not in cur]
        scope = "none" if not (changed or added or deleted) else "incremental"
        if scope != "none":
            os.makedirs(cache_dir, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({"schema_version": "1.0", "root_hash": root_hash, "files": cur}, f, ensure_ascii=False)
    data = {
        "cached": cached and prev is not None,
        "root_hash": root_hash,
        "changed_files": sorted(changed),
        "added_files": sorted(added),
        "deleted_files": sorted(deleted),
        "rebuild_scope": scope,
    }
    status = STATUS_OK
    return envelope(TOOL, status, data), EXIT_OK


def self_check():
    """--self-check：用一个临时目录自检 scan + 增量判定不崩。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "a.py")
        with open(p, "w") as f:
            f.write("x = 1\n")
        cd = os.path.join(td, "cache")
        payload, code = run(td, cd)
        assert payload["data"]["rebuild_scope"] == "full"
        # 再跑一次，无变更 → none
        payload2, code2 = run(td, cd)
        assert payload2["data"]["rebuild_scope"] == "none"
        # 改文件 → incremental
        with open(p, "a") as f:
            f.write("y = 2\n")
        payload3, code3 = run(td, cd)
        assert payload3["data"]["rebuild_scope"] == "incremental"
    return envelope(TOOL, STATUS_OK, {"self_check": "pass"}), EXIT_OK


def main():
    ap = argparse.ArgumentParser(prog="cache.py")
    ap.add_argument("--root", help="项目根路径")
    ap.add_argument("--cache-dir", help="缓存目录")
    ap.add_argument("--self-check", action="store_true", help="自检模式")
    args = ap.parse_args()
    if args.self_check:
        payload, code = self_check()
        emit(payload)
        return code
    if not args.root or not args.cache_dir:
        emit(envelope(TOOL, STATUS_ERROR, {}, [err("MISSING_ARG", "--root 和 --cache-dir 必填")]))
        return EXIT_ERROR
    payload, code = run(args.root, args.cache_dir)
    emit(payload)
    return code


if __name__ == "__main__":
    sys.exit(main())
