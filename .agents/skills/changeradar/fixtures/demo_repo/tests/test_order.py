# -*- coding: utf-8 -*-
"""订单相关单测，演示测试耦合（直调 OrderModel/OrderService）。"""
from models.order import OrderModel
from services.order_service import OrderService


def test_order_total():
    o = OrderModel()
    assert o.total([{"price": 100, "qty": 2}]) == 200


def test_order_validate():
    o = OrderModel()
    assert o.validate({"amount": 10}) is True


def test_create_order():
    svc = OrderService()
    r = svc.create_order("bob", [{"price": 10, "qty": 1}])
    assert r["payload"]["user"] == "bob"
