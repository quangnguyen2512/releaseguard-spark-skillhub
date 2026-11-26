# ChangeRadar

> 基于调用图的影响面分析与测试选择 Skill——LLM 负责理解输入与编排管线、解释报告，全部确定性计算（调用图构建、变更解析、影响传播、测试选择）由纯 Python 标准库脚本离线执行。

## 一、核心能力

ChangeRadar 支持三种输入模式，统一输出"影响面 + 该跑哪些测试"的分层风险报告：

- **diff 模式**：粘贴 `git diff` 输出 → 解析变更行映射到调用图函数 → 传播影响面 → 选出回归测试清单。
- **commit-range 模式**：给出 `A..B` 提交区间与项目路径 → 自动取 diff → 同 diff 模式后续管线（需项目内有 `.git`，可用 `rebuild_history.sh` 重建历史）。
- **rootcause 模式**：粘贴 Python Traceback → 栈帧映射到调用图节点 → 反向回溯定位根因候选并按置信度排序。

六个确定性脚本（`scripts/`，均支持 `--self-check` 自检）：

| 脚本 | 职责 |
|---|---|
| `cache.py` | 文件哈希增量缓存，判断全量/增量/复用 |
| `callgraph.py` | AST 符号表 + 调用图构建 |
| `diffparse.py` | git diff → 变更行 → 函数映射（支持 `--diff` 与 `--range`） |
| `propagate.py` | 图传播 + fan-in 截断 + 置信度分档 |
| `testselect.py` | 测试静态耦合映射 + 风险排序 |
| `stacktrace.py` | 报错栈 → 调用图节点映射 + 根因回溯 |

## 二、快速上手

### 1. 环境要求

Python ≥ 3.8，零第三方依赖（纯标准库）；`commit-range` 模式需 `git` CLI（2.x+）。

### 2. 重建 fixture 历史（首次必跑）

v3 起不再内置 `.git/` 目录（规避平台无扩展名文件告警与扫描合规要求），需先一键重建 demo 仓库的 5-commit 历史：

```bash
cd fixtures/demo_repo && bash rebuild_history.sh
```

预期末行输出 `✅ Hash match: HEAD = 8a5e665da296c34ca915be665b1eb2e11cbfc1ec`，且 `97aa988..8a5e665` 区间可用于 commit-range 演示。`.git/` 已存在时脚本会备份后重建，不删除原目录。

### 3. 端到端管线一条命令链

从包根目录执行（stdout 重定向即各步 JSON 产出）：

```bash
# Step 1 — 调用图构建
python scripts/callgraph.py --root fixtures/demo_repo > cg.json
# → 48 nodes / 27 edges

# Step 2 — 变更解析（commit-range 模式）
python scripts/diffparse.py --range 97aa988..8a5e665 \
    --repo fixtures/demo_repo --graph cg.json > dp.json
# → 1 change / 1 commit

# Step 3 — 影响面传播
python scripts/propagate.py --graph cg.json --changes dp.json > prop.json
# → 5 impact / 2 seeds

# Step 4 — 测试选择
python scripts/testselect.py --impact prop.json --graph cg.json \
    --tests fixtures/demo_repo/tests > ts.json
# → 4/7 tests selected / compression 42.9% / impact_coverage 0.8
```

### 4. 脚本自检

```bash
for s in cache callgraph diffparse propagate testselect stacktrace; do
    python scripts/$s.py --self-check && echo "$s ok"
done
```

六脚本均返回 exit 0 / status=ok 即环境就绪。`diff` 模式不依赖 `.git`，可直接用 `examples/sample_diff.txt` 跑 `diffparse.py --diff examples/sample_diff.txt --graph cg.json`。

## 三、目录结构

```
changeradar/
├── SKILL.md                      # Skill 主体：能力边界铁律 + 编排 checklist + 工具契约
├── reference.md                  # 按需加载：报告模板 / 澄清话术 / 降级矩阵 / 根因流程
├── README.md                     # 本文件
├── scripts/                      # 6 个确定性脚本 + _envelope.py（统一 JSON 信封）+ __init__.py
├── fixtures/
│   └── demo_repo/                # 内嵌 fixture 仓库（含 rebuild_history.sh 重建 git 历史）
│       ├── models/ services/ utils/ tests/  # 跨文件直调 / 继承 / 动态派发 / 装饰器 / 测试耦合
│       └── rebuild_history.sh    # 确定性重建 5-commit 历史（HEAD = 8a5e665）
├── benchmark/                    # 基准测试框架（harness.py + mutate.py + bench 结果 JSON）
├── templates/
│   └── report_template.md        # 三层报告骨架（机器 JSON / 分层摘要 / 量化指标）
├── examples/                     # 示例输入（sample_diff.txt / sample_stacktrace.txt）
└── tests/
    ├── prompt_eval/              # 24 条提示词评测用例集（开发资产，不进 Skill 引用链）
    └── test_*.py                 # 各脚本单元测试（cache/callgraph/diffparse/propagate/testselect/stacktrace）
```

包内共 44 个文件（含本 README），单文件最大 25KB。

## 四、依赖与限制

- **Python 版本**：≥ 3.8；纯标准库，零第三方依赖，离线可跑。
- **调用图覆盖**：当前仅支持 Python 项目（AST 解析）；Java / Go 等语言会被 `callgraph` 拒收并提示。
- **`.git` 重建**：v3 起不再内置 `.git/`（平台扫描合规：避免无扩展名文件告警 + 降低包体积）。`commit-range` 模式前需在 `fixtures/demo_repo/` 下跑 `rebuild_history.sh` 重建；脚本非破坏性——`.git/` 已存在时备份后重建，不删除。
- **根因模式**：仅支持 Python Traceback 栈帧映射；非 Python 栈（Java `at com.` / Go `goroutine`）会被 `stacktrace.py` 拒收（exit 2，`NON_PYTHON_STACK`）。
- **降级原则**：每步脚本 status=1（partial）继续管线并标注、status=2（error）走降级分支给明确反馈，任何路径都输出"部分结果 + 置信度声明"，永不空白返回。

## 许可证

MIT（见 `SKILL.md` frontmatter `license` 字段）。
