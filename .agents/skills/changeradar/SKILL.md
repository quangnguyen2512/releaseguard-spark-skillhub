---
name: changeradar
license: MIT
description: |
  变更影响面分析与精准测试选择。粘贴 git diff、commit range 或报错栈，
  自动构建调用图、传播影响面、输出"该跑哪些测试"的精准清单 + 分层风险报告。
  触发词：影响面 / 回归测试 / 改了这行 / 该跑哪些测试 / 变更影响 /
  diff 分析 / commit range / 报错栈定位 / 根因定位 / 报错栈根因 / 哪些测试会挂 /
  调用图 / 代码变更影响范围。
---

## 1. 能力边界声明（铁律）

本 Skill 全部确定性计算由 scripts/ 完成，LLM 不做图/数值计算。

三权分立判定标准：**如果这个结论错了，责任能不能归因到一段可单测的代码？**
- 能 → 脚本做（cache / callgraph / diffparse / propagate / testselect / stacktrace）
- 不能（开放文本的理解与表达）→ LLM 做（理解输入、串联管线、解释报告）

三条不可逾越的红线：
1. LLM 永不自己算影响面、永不输出图结构。
2. LLM 永不输出会被下游当事实消费的数字（节点数、压缩率、召回率等）——数字只透传脚本 JSON。
3. 无脚本 JSON 输出不做任何解读——收到 status=error 或 schema_version 不匹配时走降级分支，不硬猜。

## 2. 理解层 Schema（Step 0 产出契约）

LLM 理解层的唯一合法产出是以下 JSON，自由文本一律不得直通下游：

```json
{
  "schema_version": "1.0",
  "mode": "diff | commit-range | rootcause（必填）",
  "target": {"path": "项目根路径（必填）", "tests_dir": "测试目录（可选，缺省由 testselect 探测）"},
  "scope": "对象（必填，字段随 mode 变，见下表）",
  "confidence": "high | low（必填，low 必须配 clarification_needed）",
  "clarification_needed": ["歧义点清单（可选；非空则不走管线，走澄清话术）"]
}
```

scope 随 mode 分叉（校验核心）：

| mode | scope 字段 | 校验规则 |
|---|---|---|
| diff | `diff_text` 或 `diff_file` 二选一必填 | diff_text 不含 `diff --git` 或 `@@` → confidence=low，提示确认是否为标准 git diff |
| commit-range | `repo`、`range` 均必填 | range 不匹配 `A..B`（hex sha）或 `HEAD~N..HEAD` 形式 → 拒收走澄清 |
| rootcause | `stacktrace_text` 必填 | 不含 `Traceback` / `File "` / `at ` 任一栈特征 → confidence=low |

全局校验规则（按序执行，任一不过即停）：
1. mode 识别：diff 特征（`diff --git`/`@@`/`+++`）→ diff；commit range 特征（`A..B`、git log 片段）→ commit-range；报错栈特征 → rootcause；语义无法确定 → confidence=low + clarification_needed，不硬猜。
2. 必填校验：target.path 缺失 → 澄清（不给默认路径——路径猜错 = 全管线白跑）。
3. 拒收而非修补：校验不过时输出 clarification_needed 并加载 reference.md 澄清话术，不编造字段值。

字段与脚本参数一一映射（无需二次解析）：`target.path` → `--root`；`scope.diff_text/diff_file` → diffparse `--diff`/stdin；`scope.repo + scope.range` → diffparse `--range --repo`；`scope.stacktrace_text` → stacktrace stdin；`target.tests_dir` → testselect `--tests`。

## 3. 工具清单

6 个脚本各自独立、可单测、纯标准库、零第三方依赖、离线可跑。
统一信封：`{schema_version: "1.0", tool, status, errors[], data}`；schema_version 不匹配 → 拒收走降级。
统一退出码：0=ok / 1=partial（部分结果可用，必须继续）/ 2=error（无可用结果，走降级）。

| 脚本 | 用途 | 输入 | 输出核心字段 | 退出码语义 |
|---|---|---|---|---|
| cache.py | 文件哈希增量缓存 | `--root --cache-dir` | cached / changed_files / rebuild_scope（full\|incremental\|none） | 0=有缓存决策 / 2=缓存不可用→全量 |
| callgraph.py | AST 符号表+调用图构建 | `--root [--cache]` | nodes[] / edges[] / stats / parse_failures | 0=完整图 / 1=部分文件解析失败但图可用 / 2=全失败 |
| diffparse.py | diff→变更行→函数映射 | `--diff` 或 stdin / `--range A..B --repo`；`--graph` 联动 node_id 映射 | changes[] / functions[].node_id / unmapped_lines / commits | 0=正常 / 1=部分函数映射失败 / 2=空 diff 或格式不可识别 |
| propagate.py | 图传播+fan-in 截断+置信度分档 | `--graph --changes [--max-distance 3] [--fanin-cap 50]` | seeds[] / impact[] / hubs[] / truncation / module_fallback / **confidence_distribution**（exact/conservative/unknown 聚合，可选字段，缺省时解释层按 impact[].confidence 现场聚合） | 0=有 impact / 1=impact 空但有 seeds / 2=无 seeds |
| testselect.py | 测试静态耦合映射+风险排序 | `--impact --graph --tests` | tests[] / metrics（total/selected/compression_ratio/impact_coverage） | 0=有选中测试 / 1=无测试目录，tests 为空 / 2=输入异常 |
| stacktrace.py | 报错栈→调用图节点映射+根因回溯 | 报错栈文本（stdin）+ `--graph`（必填）`[--changes diffparse.json] [--max-distance 3]` | frames[]{file,line,func,node_id,matched,raw} / root_cause_candidates[]{node_id,reason,confidence,distance} / unparsed_lines[] / truncation{max_distance,reached} | 0=全帧映射 / 1=部分帧匹配或栈截断 / 2=无法解析或非 Python 栈 |

## 4. 编排流程 Checklist

逐步执行，每步先看脚本输出 status 再决定下一步；跳步 = 下一步输入缺失 = 管线自然中断，不允许跳步。

- [ ] **Step 0 — 理解输入**：按第 2 节 Schema 输出 mode JSON。clarification_needed 非空 → 加载 reference.md 澄清话术，不进管线。
- [ ] **Step 0.5 — 环境自检**：`python scripts/<name>.py --self-check` 全部返回 0 才进入管线；失败 → 提示用户检查 Python 环境。
- [ ] **Step 1 — 缓存检查**：`python scripts/cache.py --root <path> --cache-dir .cr_cache`
  - rebuild_scope=none → 复用缓存图，跳 Step 2
  - rebuild_scope=incremental → Step 2 带 `--cache` 只重建变动文件子图再合并
  - rebuild_scope=full / cached=false → Step 2 全量构建
- [ ] **Step 2 — 调用图构建**：`python scripts/callgraph.py --root <path> [--cache .cr_cache/graph.json]`
  - status=1 → 继续，报告中标注 parse_failures 数量
  - status=2 → 降级：告知"无法解析项目结构，请确认路径指向 Python 项目"，终止
- [ ] **Step 3 — 变更解析**（diff / commit-range 模式）：
  - diff：`python scripts/diffparse.py --diff <file> --graph <callgraph.json>`（或 diff 经 stdin）
  - commit-range：`python scripts/diffparse.py --range A..B --repo <path> --graph <callgraph.json>`
  - **`--graph` 必传**：漏传时脚本不静默降级——stderr 打 WARNING 且 errors[] 含 `NO_GRAPH`，functions[].node_id 全 null，下游 impact 退化为模块级 seed。编排层见此错误码 → 补传 `--graph` 重跑本步；仅在用户明确只要模块级粗粒度时才放行并在报告中标注精度降级。
  - status=1 → 继续，部分函数 node_id=null 落 unmapped_lines 兜底
  - status=2 → 降级：空 diff / 格式不可识别 → 引导用户重新提供标准 git diff，终止
- [ ] **Step 4 — 影响面传播**：`python scripts/propagate.py --graph <callgraph.json> --changes <diffparse.json>`
  - status=1 → impact 为空但有 seeds → 报告"变更未传播到其他函数，回归风险较低"，继续 Step 5
  - status=2 → 无 seeds（变更全在模块级代码）→ 降级：按 module_fallback 报模块级保守影响，跳 Step 5 直进 Step 6
- [ ] **Step 5 — 测试选择**：`python scripts/testselect.py --impact <propagate.json> --graph <callgraph.json> --tests <tests_dir>`
  - status=1 → 无测试目录 → 输出影响面但无测试清单，标注"未找到测试目录"
  - status=2 → 输入异常 → 跳过测试选择，只输出影响面
- [ ] **Step 6 — 汇总解释**：加载 reference.md 报告模板做三层输出——机器 JSON 层（透传脚本输出，一字不改）/ 分层摘要层（槽位填充，每句论断挂 `← source:` 字段引用）/ 量化指标层（透传 metrics）。槽位无值 = 省略该段并标注「数据缺失」，禁止编造。

**rootcause 分支**（mode=rootcause）：Step 0 解析为 rootcause → 跳 Step 1/3/4/5 → Step 2 构建调用图 → 报错栈经 stdin 喂 `python scripts/stacktrace.py --graph <callgraph.json> [--max-distance 3]`（用户同时提供了 diff 时，先按 Step 3 跑 diffparse 得到 diffparse.json，追加 `--changes <diffparse.json>`，命中最近变更函数的候选 reason 升级为 `changed_recently`）→ 按 root_cause_candidates 排序输出根因候选（reason 三档：last_project_frame 栈底首帧 > nearest_to_seed 反向 BFS 调用方 > changed_recently 命中最近变更；confidence 随 distance 分档：0=exact / 1-2=conservative / ≥3=unknown）→ Step 6 按 reference.md §4 根因模板汇总。
- status=1（部分帧匹配或栈截断）→ 继续，报告中标注 unparsed_lines 数量与 truncation.reached
- status=2（无法解析或非 Python 栈）→ 降级：errors[].code=NON_PYTHON_STACK 时告知"当前仅支持 Python 栈"，引导用户粘贴 Python Traceback，终止

## 5. 降级与异常

原则：部分结果 + 置信度降级，永不崩溃，永不空白返回。完整降级矩阵（10 类异常场景 × 触发条件 × 行为定义）见 reference.md，关键三条：
1. status=1（partial）→ 永远继续管线，报告中标注受影响环节。
2. status=2（error）→ 走对应降级分支，给用户明确反馈，不硬猜。
3. hubs 非空（fan-in 超阈枢纽）→ 不展开其调用方，报告单独成段警告"建议对枢纽函数全量回归"——影响面永远收敛为可操作清单。

## 6. 上下文预算控制

本文件只放每次触发必用的内容：铁律、理解层 Schema、工具清单、管线 Checklist。以下内容按需加载 reference.md：澄清话术（Step 0 校验失败时）、报告模板与解释层三条硬约束（Step 6 时）、降级矩阵（异常时）、rootcause 模式详细流程（rootcause 分支触发时，§4）。tests/prompt_eval/ 评测用例集为开发资产，不进引用链。
