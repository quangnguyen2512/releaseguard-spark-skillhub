# -*- coding: utf-8 -*-
"""通用 helper，演示 import * 与高扇入枢纽。"""
from utils.decorators import log_call, memo  # noqa: F401


@log_call
def format_price(cents):
    """格式化价格（高扇入枢纽，被多处调用）。"""
    return f"{cents / 100:.2f}"


@memo
def normalize(name):
    """归一化名称。"""
    return name.strip().lower()
