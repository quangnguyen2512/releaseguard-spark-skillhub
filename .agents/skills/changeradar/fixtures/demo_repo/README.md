# demo_repo

ChangeRadar 内嵌 fixture 仓库。覆盖：
- 跨文件直调：services/order_service.py → models/order.py
- 单继承 + override：models/order.py::OrderModel(BaseModel) override validate
- 单继承无 override：models/user.py::UserModel
- 动态派发 unknown-dispatch：services/registry.py（getattr 字符串分发）
- 装饰器边：utils/decorators.py（log_call / memo）
- import *：app.py from utils.helpers import *
- 高扇入枢纽：utils/helpers.py::format_price
- 模块级常量：config.py（unmapped_lines 兜底）
- 测试耦合：tests/test_order.py / test_user.py / test_helpers.py

git 历史 ≥5 commit，含 1 个 bugfix commit（message 带 fix）可做代理 ground truth。
