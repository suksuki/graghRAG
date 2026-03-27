# INSIGHT DECISION BOARD（周度决策面板，v1.0 冻结结构）

> 目的：用最少数据，做出一个明确产品决策  
> 原则：每周只做 **1 个判断 + 1 个动作**
>
> 核心原则：**决策权不来自数据本身，而来自数据质量。**
>
> 冻结约束：本机制在未经历 **>= 3 次有效裁决** 前，不再修改结构（仅允许补充结果与周度记录）。

## 一、本周背景

- 时间范围：YYYY-MM-DD ～ YYYY-MM-DD
- 数据来源：`insight_events`
- 样本量（session）：_____
- 数据完整性：高 / 中 / 低
  - 高：session > 50
  - 中：20 ~ 50
  - 低：< 20（仅做观察，不做结构性决策）

## 二、核心指标（SQL + 结果）

### 1) Doc Scope 使用率

```sql
SELECT
  COUNT(*) FILTER (WHERE event = 'query_with_doc_scope') * 1.0
  / NULLIF(COUNT(*) FILTER (WHERE event = 'query_submitted'), 0)
FROM insight_events;
```

结果：`_____`

### 2) Scope 转化率（选择 -> 使用）

```sql
SELECT
  COUNT(*) FILTER (WHERE event = 'query_with_doc_scope') * 1.0
  / NULLIF(COUNT(*) FILTER (WHERE event = 'select_doc_scope'), 0)
FROM insight_events;
```

结果：`_____`

### 3) 证据点击率（Scoped vs Global）

```sql
WITH scoped AS (
  SELECT session_id
  FROM insight_events
  WHERE event = 'query_with_doc_scope'
),
global AS (
  SELECT session_id
  FROM insight_events
  WHERE event = 'query_submitted'
    AND (payload->>'has_doc_scope') = 'false'
),
clicks AS (
  SELECT session_id
  FROM insight_events
  WHERE event = 'click_reference'
)
SELECT
  'scoped' AS type,
  COUNT(DISTINCT c.session_id) * 1.0 / NULLIF(COUNT(DISTINCT s.session_id), 0) AS click_rate
FROM scoped s
LEFT JOIN clicks c USING (session_id)
UNION ALL
SELECT
  'global' AS type,
  COUNT(DISTINCT c.session_id) * 1.0 / NULLIF(COUNT(DISTINCT g.session_id), 0) AS click_rate
FROM global g
LEFT JOIN clicks c USING (session_id);
```

scoped：`_____`  
global：`_____`

## 三、Session 定性观察（5~10 个）

记录真实行为路径（至少 5 个）：

### Session #1

```text
select_doc -> query -> click -> stop
```

判断：理解清晰

### Session #2

```text
query -> hover -> switch -> switch -> 无 click
```

判断：conflict 困惑

（继续补充 Session #3~#10）

## 四、关键判断（只能选一个）

- [ ] Doc Scope 有明显价值（更高点击率）
- [ ] Doc Scope 被使用，但价值不明显
- [ ] Doc Scope 几乎未被使用
- [ ] 使用后反而更困惑

本周结论（不超过 20 字）：

```text
_____
```

## 五、行动决策（只能做一个）

若 “有价值”：
- [ ] 强化入口（默认提示）
- [ ] 提高可见性（位置/文案）

若 “使用但弱”：
- [ ] 优化文案（强调“仅基于该文档”）
- [ ] 优化提示（引导点击证据）

若 “未使用”：
- [ ] 不加功能，仅优化引导
- [ ] 保持现状再观察一周

若 “更困惑”：
- [ ] 暂不强化
- [ ] 检查检索/摘要质量

本周执行动作（只写一个）：

```text
_____
```

## 六、禁止事项（每周提醒）

- 不新增功能
- 不改 UI 结构
- 不做多变量实验
- 不同时改两件事

## 七、固定节奏

1. 跑 SQL（10 分钟）
2. 看 5 个 session（20 分钟）
3. 写结论（5 分钟）
4. 做一个动作（开发 < 1 小时）

> 核心：用最小成本，持续收敛产品方向。

## 八、决策防抖

- 同一结论需连续 2 周出现，才允许做结构性调整。
- 若本周“数据完整性=低”，默认进入观察周，不做结构改动。

## 九、采样周验收线

进入“首次有效裁决周”前，必须同时满足：

1. `query_submitted >= 50`
2. 非测试 session 占比 `>= 80%`
3. 不同 session 数 `>= 20`

未满足时：

- 自动进入观察周（仅记录，不允许产品调整）
- 结论统一使用：**“尚无有效查询样本，无法评估 Doc Scope 使用情况”**

## 十、数据来源标记

每周必须标记主要数据来源（可多选）：

- 内部测试
- 邀请用户
- 真实用户（自然流量）

执行规则：

- 若主要数据来源为“内部测试”或“邀请用户”：
  - 仅允许执行 L1（文案）动作
  - 不允许执行 L2/L3/L4（可见性/交互/结构）调整
- 仅当“真实用户（自然流量）”成为主要来源时，才允许按常规分级执行 L2 及以上动作

> 治理原则：**没有数据，比错误数据更安全。**

## 十一、决策信心等级

每周必须给出本周裁决信心：`高 / 中 / 低`。

### 评级规则

- 高：
  - 数据完整性 = 高
  - 主要来源 = 真实用户（自然流量）
  - 核心指标方向一致
  - 同结论连续 2 周
- 中：
  - 数据完整性 = 中；或
  - 来源混合（真实 + 邀请/内部）；或
  - 指标轻微冲突（定量与定性存在张力）
- 低：
  - 数据完整性 = 低；或
  - 主要来源仅内部/邀请；或
  - 关键指标缺失/不可计算

### 动作门控

- 低：仅允许观察，不允许动作
- 中：允许 L1/L2，不允许 L3/L4
- 高：允许按分级执行（含 L3/L4）

