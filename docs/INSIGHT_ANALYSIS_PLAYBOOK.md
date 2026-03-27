# INSIGHT ANALYSIS PLAYBOOK (v0)

目标：把行为数据转成明确的产品动作，避免“看了数据但不敢决策”。

## 一、分析目标

我们不评估“答案正确性”，只评估：

- 用户是否更容易进入证据（`[n]`）
- 用户是否在冲突结构中迷失
- 是否需要开启结构解释层（v3-A）

## 二、分组口径（固定）

基于 `insight_events.doc_id`：

- `global`：`doc_id = '__search__'`
- `doc_scoped`：`doc_id <> '__search__'`

> 注：本口径与当前 `SearchPage` 埋点实现一致。若后续改动 sentinel 值，需同步更新本文件与 SQL。

## 三、核心指标与硬规则

### 1) Evidence Click Rate（证据点击率）

定义：每个 session 的证据点击强度（点击是否发生、平均点击次数）。

决策规则：

- 若 `doc_scoped > global * 1.2`  
  - 结论：doc 模式更易理解  
  - 动作：强化 doc 模式入口与引导文案
- 若 `click_rate < 0.30`  
  - 结论：用户未进入证据层  
  - 动作：优化 summary 提示与点击引导

### 2) Conflict Exploration Rate（冲突探索率）

定义：`switch_conflict_group / session`。

决策规则：

- 若 `switch_rate > 1.5`  
  - 结论：冲突区切换偏高，可能结构困惑
- 若同时满足 `click_rate < 0.30`  
  - 结论：典型 confused exploration  
  - 动作：进入 v3 触发候选池

### 3) Stuck Rate（停留不点击）

定义：`conflict` 区停留 > 5s 且 session 内无 `click_reference`。

决策规则：

- 若 `stuck_rate > 0.25`  
  - 结论：存在明确认知阻塞  
  - 动作：开启 v3-A 实验

### 4) Evidence Engagement Score（EES）

定义：`click_reference / total_events`（session 粒度再聚合）。

决策规则：

- 若 `doc_scoped EES > global EES`  
  - 结论：doc 模式更可理解  
  - 动作：提高 doc 模式曝光与默认推荐
- 若 `EES < 0.15`  
  - 结论：行为未进入证据路径  
  - 动作：调整入口提示和摘要交互引导

## 四、v3-A 开关规则（上线前）

满足任一即可进入“开启候选”：

1. `stuck_rate > 25%`
2. `switch_rate > 1.5` 且 `click_rate < 30%`
3. `friction_v3_candidates` 中 `suggested_v3 = 'A'` 占比 > 40%

不建议开启 v3 的条件：

1. `click_rate > 50%`
2. `stuck_rate < 10%`

解释：用户已能理解证据结构，无需增加解释层负担。

## 五、session 定性抽样（每轮必须做）

每轮至少抽样 5~10 个 session（按时间最近优先）。

观察清单：

- hover 多但不点击
- group 间来回切换
- 点击后仍高频切换
- 停留位置：`summary` / `conflict` / `group`

标注类型：

- A：数量困惑
- B：来源困惑
- C：时间冲突
- D：语义冲突

用途：校验 “friction -> suggested_v3” 是否贴近真实困惑。

## 六、产品动作映射

### 情况 1：doc_scoped 明显更优

- 动作：强化 doc 上传入口与入口文案
- 动作：在全局入口增加“限定文档更易对照证据”的提示

### 情况 2：global 摩擦高

- 动作：优先在 global 模式试验 v3-A
- 动作：只在冲突区显示结构解释，避免全页干扰

### 情况 3：conflict 区摩擦集中

- 动作：v3 触发范围收敛到 conflict 区（局部解释）

### 情况 4：整体点击率低

- 动作：优化 summary 文案和 `[n]` 引导样式
- 动作：保留“非对话、单次问题”提示，防止 Chat 预期偏移

## 七、强约束原则

- 禁止因为数据直接引入“对错判断”
- 禁止生成可信度评分或裁判性结论
- v3 仅解释结构，不替用户裁决

## 八、执行节奏（每轮 40 分钟）

1. 跑 SQL（10 分钟）
2. 看 5 个 session 回放（20 分钟）
3. 做 1 个产品决策（10 分钟）

目标：快节奏、小步决策，避免分析瘫痪。

## 九、与现有文档关系

- 指标 SQL：见 `docs/INSIGHT_EVENTS.md`
- 本文负责“阈值 -> 动作”映射，不重复 SQL 细节

