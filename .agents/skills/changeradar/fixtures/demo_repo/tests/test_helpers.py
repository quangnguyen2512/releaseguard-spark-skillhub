# -*- coding: utf-8 -*-
"""helpers 单测。"""
from utils.helpers import format_price, normalize


def test_format_price():
    assert format_price(100) == "1.00"


def test_normalize():
    assert normalize("  Alice  ") == "alice"
