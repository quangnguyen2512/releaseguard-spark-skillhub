#!/bin/bash
# rebuild_history.sh — 确定性重建 demo_repo 的 5-commit git 历史
#
# 用途：changeradar-final-v2.zip 不再内嵌 .git/ 目录（规避平台无扩展名文件告警），
#       评测现场运行本脚本即可一键还原与原版完全一致的 commit 历史。
#
# 用法：cd fixtures/demo_repo && bash rebuild_history.sh
# 依赖：git CLI（任何 2.x+ 版本）
# 预期产出：5 个 commit，HEAD = 8a5e665da296c34ca915be665b1eb2e11cbfc1ec
#          commit range 97aa988..8a5e665 用于 diffparse commit-range 模式演示
#
# 确定性保证：所有 author/committer name/email/date 均通过环境变量固定，
#             文件内容与原始 fixture 逐字节一致，commit 哈希可精确复现。

set -euo pipefail
cd "$(dirname "$0")"

# ── 备份既有历史 & 初始化 ──────────────────────────────────────
# 非破坏性方案：若 .git/ 已存在，重命名备份而非删除，绝不丢数据。
if [ -d .git ]; then
    BACKUP_DIR=".git.bak.$(date +%s)"
    echo "检测到已存在的 .git/ 目录，备份为 ${BACKUP_DIR} 后重建（不删除任何数据）"
    mv .git "$BACKUP_DIR"
fi
git init -q
git config user.name "ChangeRadar Demo"
git config user.email "demo@changeradar.local"
git config commit.gpgsign false

export GIT_AUTHOR_NAME="ChangeRadar Demo"
export GIT_AUTHOR_EMAIL="demo@changeradar.local"
export GIT_COMMITTER_NAME="ChangeRadar Demo"
export GIT_COMMITTER_EMAIL="demo@changeradar.local"

# ── Commit 1: init — base model + config ──────────────────────
#   文件：config.py, models/__init__.py, models/base.py
#   预期哈希：e3869c8a99382fd23de5b26f630f1ae737d40a86
GIT_AUTHOR_DATE="1786239812 +0800" GIT_COMMITTER_DATE="1786239812 +0800" \
  git add config.py models/__init__.py models/base.py
GIT_AUTHOR_DATE="1786239812 +0800" GIT_COMMITTER_DATE="1786239812 +0800" \
  git commit -q -m "init: add base model and config"

# ── Commit 2: OrderModel + UserModel ──────────────────────────
#   新增：models/order.py（正确版）, models/user.py
#   预期哈希：71cddd87bf672deb273b63e53642a590b503e672
GIT_AUTHOR_DATE="1786239814 +0800" GIT_COMMITTER_DATE="1786239814 +0800" \
  git add models/order.py models/user.py
GIT_AUTHOR_DATE="1786239814 +0800" GIT_COMMITTER_DATE="1786239814 +0800" \
  git commit -q -m "feat: add OrderModel with override and UserModel"

# ── Commit 3: services + utils + tests + app ──────────────────
#   新增：README.md, app.py, services/, utils/, tests/
#   预期哈希：ce1905b4957627c0b76451cb4562adc77ebfe37d
GIT_AUTHOR_DATE="1786239818 +0800" GIT_COMMITTER_DATE="1786239818 +0800" \
  git add README.md app.py services/ utils/ tests/
GIT_AUTHOR_DATE="1786239818 +0800" GIT_COMMITTER_DATE="1786239818 +0800" \
  git commit -q -m "feat: add order service, decorators, helpers and tests"

# ── Commit 4: refactor — 引入缺陷 ─────────────────────────────
#   修改：models/order.py → 简化版（amount>=0 而非 >0，total 漏乘 qty）
#   预期哈希：97aa9884324c3a1e01ddb2f01d14a0535d580c23

# 保存正确版本以备 commit 5 恢复
cp models/order.py .order_correct.py.bak

cat > models/order.py << 'BUGGY_EOF'
# -*- coding: utf-8 -*-
"""Order 模型，演示单继承 override + 跨文件直调。"""
from models.base import BaseModel


class OrderModel(BaseModel):
    """订单模型。"""

    def __init__(self, name="order"):
        super().__init__(name)

    def validate(self, data):
        """override：订单需 amount>=0（缺陷：应为 >0）。"""
        super().validate(data)
        if data.get("amount", 0) < 0:
            raise ValueError("amount 不能为负")
        return True

    def total(self, items):
        """计算订单总额（缺陷：漏乘 qty，只累加 price）。"""
        return sum(i.get("price", 0) for i in items)
BUGGY_EOF

GIT_AUTHOR_DATE="1786239820 +0800" GIT_COMMITTER_DATE="1786239820 +0800" \
  git add models/order.py
GIT_AUTHOR_DATE="1786239820 +0800" GIT_COMMITTER_DATE="1786239820 +0800" \
  git commit -q -m "refactor: simplify order total calculation"

# ── Commit 5: fix — 恢复正确版本 ──────────────────────────────
#   修改：models/order.py → 恢复正确版（amount>0，total 乘 qty）
#   预期哈希：8a5e665da296c34ca915be665b1eb2e11cbfc1ec
mv .order_correct.py.bak models/order.py
GIT_AUTHOR_DATE="1786239821 +0800" GIT_COMMITTER_DATE="1786239821 +0800" \
  git add models/order.py
GIT_AUTHOR_DATE="1786239821 +0800" GIT_COMMITTER_DATE="1786239821 +0800" \
  git commit -q -m "fix: order total must multiply price by qty and validate amount>0"

# ── 验证 ───────────────────────────────────────────────────────
echo "=== Rebuilt git history ==="
git log --oneline

HEAD_HASH=$(git rev-parse HEAD)
EXPECTED="8a5e665da296c34ca915be665b1eb2e11cbfc1ec"
if [ "$HEAD_HASH" = "$EXPECTED" ]; then
    echo ""
    echo "✅ Hash match: HEAD = $HEAD_HASH"
    echo "✅ Commit range 97aa988..8a5e665 ready for diffparse --range demo"
else
    echo ""
    echo "⚠️  Hash mismatch: got $HEAD_HASH, expected $EXPECTED"
    echo "    (functional equivalence preserved; update docs if needed)"
fi
