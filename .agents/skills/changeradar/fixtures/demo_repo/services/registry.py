# -*- coding: utf-8 -*-
"""动态派发注册表，演示 getattr / 字符串分发的 unknown-dispatch。"""


class HandlerRegistry:
    """按名字分发 handler，静态不可枚举 → unknown-dispatch。"""

    def __init__(self):
        self._handlers = {}

    def register(self, name, fn):
        self._handlers[name] = fn

    def dispatch(self, name, *args, **kwargs):
        """getattr 动态分发。"""
        handler = getattr(self, "_h_" + name, None)
        if handler:
            return handler(*args, **kwargs)
        fn = self._handlers.get(name)
        if fn:
            return fn(*args, **kwargs)
        raise KeyError(name)

    def _h_default(self, x):
        return x
