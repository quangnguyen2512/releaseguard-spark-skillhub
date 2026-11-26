# -*- coding: utf-8 -*-
"""用户单测。"""
from models.user import UserModel


def test_display_name():
    u = UserModel("alice")
    assert u.display_name() == "ALICE"


def test_user_save():
    u = UserModel()
    r = u.save({"x": 1})
    assert r["payload"] == {"x": 1}
