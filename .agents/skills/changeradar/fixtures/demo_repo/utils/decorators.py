# -*- coding: utf-8 -*-
"""装饰器集合，演示 decorator 边。"""


def log_call(fn):
    """调用日志装饰器。"""
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)
    return wrapper


def memo(fn):
    """记忆化装饰器。"""
    cache = {}
    def wrapper(*args):
        if args not in cache:
            cache[args] = fn(*args)
        return cache[args]
    return wrapper
