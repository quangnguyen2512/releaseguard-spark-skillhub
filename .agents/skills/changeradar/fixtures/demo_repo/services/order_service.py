# -*- coding: utf-8 -*-
"""订单服务，跨文件直调 OrderModel / UserModel。"""
from models.order import OrderModel
from models.user import UserModel


class OrderService:
    """订单业务服务。"""

    def __init__(self):
        self.order = OrderModel()
        self.user = UserModel()

    def create_order(self, user_name, items):
        """创建订单。"""
        self.user = UserModel(user_name)
        data = {"user": user_name, "amount": self.order.total(items), "items": items}
        self.order.validate(data)
        return self.order.save(data)

    def cancel_order(self, order_id):
        """取消订单（stub）。"""
        return {"cancelled": order_id}
