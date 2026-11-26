# ChangeRadar · Reference

> 按需加载的扩展材料。SKILL.md 只放理解 schema + 管线 checklist + 铁律（短篇幅），本文件收纳：澄清话术、报告模板（含 rootcause 三层骨架）、降级矩阵、根因模式详细流程（Day3 已填实）、上下文预算说明。
> 触发条件：理解层校验失败 → 加载澄清话术；Step 6 解释层填充 → 加载报告模板；管线任意步骤 status=2 → 加载降级矩阵；mode=rootcause → 加载根因模式（Day3 启用）。
> 加载方式：编排层按需 `read reference.md` 后**只引用本文件的具体小节**，不要整文件塞进上下文。

---

## 1. 澄清话术（6 类，校验失败时按类型取用）

**原则**：给选项不给开放题。每次澄清附候选解释，用户点选即可，一轮收敛。话术末尾不追加追问"还有其他需要吗"——避免无止境多轮。

| # | 歧义类型 | 触发条件 | 话术模板 |
|---|---|---|---|
| C1 | mode 不明 | 自然语言无语义指向（无 diff 头/无 range 特征/无栈特征） | 「你想分析的是哪种输入？① 一段 git diff（改动内容）② 一段 commit 区间（如 A..B）③ 一段报错栈（定位根因）」 |
| C2 | 模块指代不清 | target/scope 出现自然语言模块名（"订单模块"） | 「你说的『订单模块』是指：① order/ 目录 ② 文件名含 order 的文件 ③ 函数名含 order 的函数？（ChangeRadar 需要落到具体路径才能建图）」 |
| C3 | diff 格式存疑 | 声明 diff 模式但无标准特征 | 「这段内容不像标准 git diff 输出（缺 `diff --git` 头）。请粘贴 `git diff` 的原始输出，或确认按纯文本变更描述处理（精度会降到模块级）。」 |
| C4 | range 格式错误 | range 校验不过 | 「commit 区间格式应为 `A..B`（如 `a1b2c3..d4e5f6` 或 `HEAD~5..HEAD`）。请确认区间写法；也可以直接粘贴 `git log --oneline` 输出，我来帮你定位。」 |
| C5 | 栈与项目不匹配 | rootcause 模式但 target.path 缺失 | 「报错栈定位需要项目根路径来构建调用图。请提供项目路径（栈帧里的文件路径应能在该项目下找到）。」 |
| C6 | 路径不存在（运行时） | 脚本返回路径错误 | 「路径 `<path>` 下未找到 Python 项目。请确认：① 路径是否指向项目根目录 ② 是否为 Python 项目（当前仅支持 Python 调用图）。」 |

---

## 2. 报告骨架模板（Step 6 解释层产出契约）

**三层结构定死，LLM 只做槽位填充**。每个叙述段落后挂 `← source: <JSON 字段路径>`，槽位无值 = 数据缺失 = 该段直接省略并标注「数据缺失」，禁止编造。

### 2.1 三层骨架（diff / commit-range 模式通用）

```
# ChangeRadar 变更影响面报告

## 第一层 · 机器 JSON（透传，零创作）
原样输出 propagate.json + testselect.json 的 data 字段，供下游工具消费。
（本层 LLM 一个字不改，只负责拼接）
# 优先读 propagate.confidence_distribution（裁决后新增字段），缺省时按 impact[].confidence 现场聚合降级。

## 第二层 · 分层摘要（槽位填充）

### 变更概览
本次变更涉及 {changes_count} 个文件、{changed_functions} 个函数。← source: diffparse.changes[]
模式：{mode}；影响面构建基于 {graph_stats.nodes} 节点 / {graph_stats.edges} 条调用边。← source: callgraph.stats

### 影响面分层
- **直接影响（exact）**：{exact_list}，共 {exact_count} 个函数 ← source: propagate.impact[confidence=exact]
- **间接影响（conservative）**：{conservative_count} 个函数（传播距离 ≤ {max_distance}）← source: propagate.impact[confidence=conservative], truncation.max_distance
- **不确定区域（unknown）**：{unknown_list}——含动态调用，按模块级保守估计 ← source: propagate.module_fallback, impact[confidence=unknown]
{IF hubs 非空} ⚠️ **高扇入枢纽**：{hub_names}（fan-in 最高 {max_fan_in}），未展开其调用方，建议对枢纽函数全量回归。← source: propagate.hubs[]

### 该跑哪些测试
从 {total_tests} 个测试中选出 {selected} 个（压缩率 {compression_ratio}）。← source: testselect.metrics
- 高风险（必跑）：{high_risk_tests} ← source: testselect.tests[risk_level=high]
- 中风险（建议跑）：{medium_risk_tests} ← source: tests[risk_level=medium]
- 低风险（可跳过）：仅列出数量 {low_count} 个 ← source: tests[risk_level=low]
影响节点被选中测试覆盖比例：{impact_coverage} ← source: testselect.metrics.impact_coverage

### 风险提示（条件段落，无数据则整段省略）
{IF status=partial 出现于任一脚本} 本报告基于部分解析结果：{partial_notes} ← source: 各脚本 errors[] + parse_failures
{IF 缓存命中} 本次复用缓存调用图（变更文件 {changed_files_count} 个）。← source: cache.rebuild_scope, changed_files

## 第三层 · 量化指标（透传 metrics，禁止改写数字）
| 指标 | 值 | 来源字段 |
| 测试总数 / 选中 / 压缩率 | ... | testselect.metrics.* |
| 影响节点数 / 占全图比例 | ... | propagate.impact, callgraph.stats |
| 置信度分布 exact/conservative/unknown | {conf_dist_json} | propagate.confidence_distribution（缺省时按 impact[].confidence 现场聚合）|
```

### 2.2 根因模式（rootcause）报告骨架（Day3 定稿，三层同构）

```
# ChangeRadar 根因定位报告

## 第一层 · 机器 JSON（透传，零创作）
原样输出 stacktrace.json 的 data 字段（frames[] / root_cause_candidates[] / unparsed_lines[] / truncation）。
（本层 LLM 一个字不改，只负责拼接）

## 第二层 · 分层摘要（槽位填充）

### 栈帧映射结果
报错栈共 {frames_total} 帧，其中 {frames_matched} 帧映射到调用图节点。← source: stacktrace.frames[].matched
{IF unparsed_lines 非空} ⚠️ 有 {unparsed_count} 行无法解析：{unparsed_lines} ← source: stacktrace.unparsed_lines[]

### 根因候选排序
- **首选根因（exact）**：{primary_node}（{primary_func}）——异常抛出点，distance=0 ← source: root_cause_candidates[reason=last_project_frame]
- **调用链回溯（conservative）**：{conservative_nodes}（传播距离 1-2 层）← source: root_cause_candidates[confidence=conservative]
{IF changed_recently 非空} ⚠️ **最近变更命中**：{changed_nodes}——这些函数在本次 diff 中被改过，根因概率升高 ← source: root_cause_candidates[reason=changed_recently]
{IF unknown 非空} **不确定区域（unknown）**：{unknown_nodes}（距离 ≥3，置信度低）← source: root_cause_candidates[confidence=unknown]

### 截断声明（条件段落，无截断则整段省略）
{IF truncation.reached} 反向回溯在 {max_distance} 层处截断，更远调用方未展开。可调大 `--max-distance` 重跑获取更深回溯。← source: stacktrace.truncation

### 风险提示（条件段落）
{IF status=partial} 本报告基于部分映射结果：{partial_notes} ← source: stacktrace.errors[]

## 第三层 · 量化指标（透传 metrics，禁止改写数字）
| 指标 | 值 | 来源字段 |
| 栈帧总数 / 映射成功 | ... | frames[].matched |
| 根因候选数（exact/conservative/unknown） | ... | root_cause_candidates[].confidence |
| 回溯最大距离 / 是否截断 | ... | truncation.* |
```

### 2.3 解释层三条硬约束（模板头部强制）

1. **数字只出现在第一、三层**（透传），第二层摘要里的数字必须是槽位填充，**禁止 LLM 自己数数**（"大约十几个函数"一律不允许）。
2. **槽位引用的 JSON 字段为空时**：该叙述段整段省略并附"数据缺失"标记，不得用"暂无""未知"等措辞掩盖。
3. **每个论断必须可回指到 JSON 字段路径**——`source: <字段>` 缺失或字段为空 = 评审追问时该句不得作为论据出现。

---

## 3. 降级矩阵（每类异常 × 行为定义）

| 异常 | 触发条件 | 行为 | 状态码 | 后续动作 |
|---|---|---|---|---|
| 空 diff | scope.diff_text 为空或仅含空白 | confidence=low，提示用户提供 diff，触发话术 C3 | status=2 | 等用户重输 |
| 解析失败 | diffparse 报告 parse_failures > 0 | 继续管线但 confidence=low，partial_notes 列出失败文件 | status=1 | 报告风险段声明 |
| 调用图为空 | callgraph 节点数 = 0 | 终止管线，提示非 Python 项目或路径错误，触发话术 C6 | status=2 | 等用户确认路径 |
| 影响面爆炸 | impact 数 > 200 或 fan-in 枢纽 > 5 | 保留 top-N + 枢纽，truncation 字段标注，报告警告段 | status=1 | 用户可调阈值重跑 |
| 多解释冲突 | 同一 commit range 跨多分支 | 选 HEAD 所在分支，影响面取并集，confidence=low | status=1 | 报告风险段 |
| 缓存污染 | 缓存 hash 与当前文件不一致 | 强制全量重建，confidence=high | status=0 | 继续 |
| 非 Python 项目 | 扫描发现无 .py 文件 | 拒收，触发话术 C6 | status=2 | 等用户换项目 |
| 栈非 Python | rootcause 模式的栈含 Java/Go 特征 | 拒收并声明当前仅支持 Python | status=2 | 引导 Day3 扩展或换工具 |
| 路径不可达 | target.path 不存在或无读权限 | 拒收，触发话术 C6 | status=2 | 等用户提供正确路径 |

**降级总原则**：宁可降级（status=1/2 + 报告声明）也不硬猜；宁可少选（漏报）也不多编（编造）；每条降级路径必须可回放（缓存 + 日志保留）。

---

## 4. rootcause 模式详细流程（Day3 已填实，字段名经实现核对）

**当前状态**：stacktrace.py 已实现并经端到端复跑（demo_repo 48 nodes / 27 edges）。本节字段名与实现逐项核对一致。理解层加载条件 = `mode=rootcause`。

### 4.1 输入
- **stdin**：用户粘贴的完整报错栈文本（Python Traceback 格式）
- `--graph`（必填）：callgraph.py 输出的 JSON 路径（建图用，编排层先跑 callgraph 再喂 stacktrace）
- `--changes`（可选）：diffparse.py 输出的 JSON 路径，用于标记最近变更函数并升级候选 reason 为 `changed_recently`
- `--max-distance`（可选，默认 3）：反向 BFS 回溯最大层数
- target.path：项目根路径（由编排层传给 callgraph 建图，stacktrace 本身只吃 graph JSON）

### 4.2 处理流程（8 步，与实现一致）
1. 栈帧正则解析（`File "..." , line N, in funcname`），跳过异常类型行与源码片段行
2. **非 Python 栈检测**：整体文本扫描 Java（`at com.` 包路径）/ Go（`goroutine` + `.go:`）特征；命中且无任何 Python `File` 帧 → 拒收（exit 2，errors[].code=NON_PYTHON_STACK）
3. 过滤项目外帧（site-packages / dist-packages / `<frozen>` / `<string>` / runpy / importlib）
4. 每帧 file+func → callgraph node_id 映射（file 后缀宽松匹配绝对路径；`<module>` 帧匹配 module 节点；`Class.method` 帧按方法名兜底匹配）
5. 标记 `last_project_frame`：栈底第一帧项目内代码（traceback 末帧 = 异常抛出点，`reversed(frames)` 取首个 matched）
6. 反向 BFS：从 last_project_frame 沿反向调用边回溯 N 层（`--max-distance`），跳过 test 节点，去重并保留更近距离
7. 根因候选排序：`last_project_frame`（distance=0）> `changed_recently`（命中 `--changes` 变更集时从 nearest_to_seed 升级）> `nearest_to_seed`（反向 BFS 调用方）；同 reason 按 distance 升序
8. confidence 分档：distance 0=`exact` / 1-2=`conservative` / ≥3=`unknown`

### 4.3 输出 data schema（经实现核对）
```json
{
  "schema_version": "1.0",
  "tool": "stacktrace",
  "mode": "rootcause",
  "status": "ok|partial|error",
  "errors": [],
  "data": {
    "frames": [
      {"file": "...", "line": N, "func": "...", "node_id": "...|null", "matched": true|false, "raw": "原始栈帧行"}
    ],
    "root_cause_candidates": [
      {"node_id": "...", "reason": "last_project_frame|nearest_to_seed|changed_recently", "confidence": "exact|conservative|unknown", "distance": N}
    ],
    "unparsed_lines": ["无法归类的行..."],
    "truncation": {"max_distance": 3, "reached": true|false}
  }
}
```
**字段说明**：
- `frames[].raw`：原始栈帧文本，供报告层展示与回溯（additive，不影响下游消费）
- `unparsed_lines[]`：无法归类为帧/异常行/源码片段的行，空数组=栈干净
- `truncation.reached`：BFS 触达 max_distance 上限 或 检测到栈截断标记（`...(truncated)`）时为 true
- reason 三档语义：`last_project_frame`=异常抛出点本身 / `nearest_to_seed`=反向回溯到的调用方 / `changed_recently`=调用方且命中最近变更（优先级高于 nearest_to_seed）

### 4.4 退出码与降级
- **exit 0**（status=ok）：全部项目帧映射成功，无截断
- **exit 1**（status=partial）：部分帧未映射（errors[].code=NO_MATCH 或 PARTIAL_MATCH）或检测到栈截断——报告照常产出，风险段声明降级
- **exit 2**（status=error）：无法解析出栈帧（NO_FRAMES）/ 非 Python 栈（NON_PYTHON_STACK）/ stdin 空（EMPTY）/ 缺 `--graph`（MISSING_ARG）——拒收，触发对应澄清话术（C5 栈与项目不匹配 / 非 Python 栈引导换工具）

报告层套用 §2.2 根因模式三层骨架。

---

## 5. 上下文预算分配（与编排工程师方案对齐）

| 文件 | 加载时机 | 预算 | 内容 |
|---|---|---|---|
| SKILL.md | 每次触发全量加载 | ~130 行 / ~2000 字 | frontmatter + 能力边界铁律 + 理解层 schema（仅 JSON 骨架与校验表） + 工具清单表 + 管线 checklist + 降级原则（3 条） |
| reference.md | 按需加载 | 任意（按节取用，不整文件入上下文） | 澄清话术（6 类） + 报告模板（三层） + 降级矩阵（9 行） + rootcause 模式流程 + 预算说明 |
| templates/report_template.md | Step 6 解释层 | 槽位填充模板 | 报告骨架的填空版（与 §2.1 一致） |
| scripts/*.py | 编排层按 checklist 调用 | 不入上下文（脚本自运行） | 5+1 脚本（Day3 含 stacktrace） |

**预算铁律**：SKILL.md 严禁超过 130 行；reference.md 严禁整文件加载（按节引用）。违反预算 = 流程漂移诱因 = 鲁棒性 30 分失分。

---

## 6. 与 Day1 评测用例集的接口

24 条评测用例（A 清晰 8 / B 模糊 6 / C 对抗 5 / D 越界 5）的预期行为全部可在本文件落地：
- 清晰组 → §2 报告模板 + SKILL.md 理解 schema
- 模糊组 → §1 澄清话术
- 对抗组 → §3 降级矩阵 + SKILL.md 铁律
- 越界组 → §1 澄清话术 + SKILL.md 能力边界声明

每条用例的预期行为可在 `tests/prompt_eval/cases.json` 中以 `expected_action: pass_to_pipeline | clarify | refuse` 标注。
