# ChangeRadar 变更影响面报告

> 本模板为 §2.1 三层骨架的填空版。LLM 仅做槽位填充，禁止编造数字。
> 槽位无值 = 数据缺失 = 该段直接省略并标注「数据缺失」。

## 第一层 · 机器 JSON（透传，零创作）

原样输出 propagate.json + testselect.json 的 data 字段，供下游工具消费。
（本层 LLM 一个字不改，只负责拼接）

> 优先读 propagate.confidence_distribution（裁决后新增字段），缺省时按 impact[].confidence 现场聚合降级。

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
|------|-----|----------|
| 测试总数 / 选中 / 压缩率 | ... | testselect.metrics.* |
| 影响节点数 / 占全图比例 | ... | propagate.impact, callgraph.stats |
| 置信度分布 exact/conservative/unknown | {conf_dist_json} | propagate.confidence_distribution（缺省时按 impact[].confidence 现场聚合）|
