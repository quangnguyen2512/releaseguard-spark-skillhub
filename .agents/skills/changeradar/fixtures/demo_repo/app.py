# -*- coding: utf-8 -*-
"""应用入口，演示跨模块调用链 + import *。"""
from services.order_service import OrderService
from utils.helpers import *  # import *：整文件 conservative
from utils.helpers import format_price, normalize


def run():
    svc = OrderService()
    items = [{"price": 100, "qty": 2}, {"price": 50, "qty": 1}]
    result = svc.create_order("alice", items)
    print(format_price(result["payload"]["amount"]))
    print(normalize(result["payload"]["user"]))
    return result


if __name__ == "__main__":
    run()
