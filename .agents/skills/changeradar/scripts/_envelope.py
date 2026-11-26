# -*- coding: utf-8 -*-
"""通用 JSON 信封与退出码约定，所有脚本共用。

信封结构（schema_version 1.0，对齐全栈代码审查官 Day1 定稿契约）：
  {schema_version, tool, status, errors[], data}

退出码：
  0 = ok      完整结果，编排层正常继续
  1 = partial 部分结果可用，编排层必须继续（不得当失败处理）
  2 = error   无可用结果，走降级分支
"""
import json, sys

SCHEMA_VERSION = "1.0"

STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_ERROR = "error"

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_ERROR = 2


def envelope(tool, status=STATUS_OK, data=None, errors=None):
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": tool,
        "status": status,
        "errors": errors or [],
        "data": data or {},
    }


def emit(payload):
    """输出 JSON 到 stdout，UTF-8、ensure_ascii=False，紧凑可解析。"""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")


def err(code, message, file=None):
    e = {"code": code, "message": message}
    if file is not None:
        e["file"] = file
    return e
