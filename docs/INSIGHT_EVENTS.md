# Insight 认知摩擦埋点（`/log`）

## 表结构（PostgreSQL）

首次写入前由 `core/insight_event_log.ensure_insight_events_table()` 自动 `CREATE TABLE IF NOT EXISTS`。也可手动执行：

```sql
CREATE TABLE IF NOT EXISTS insight_events (
    id BIGSERIAL PRIMARY KEY,
    event TEXT NOT NULL,
    ts BIGINT NOT NULL,
    session_id TEXT NOT NULL,
    doc_id TEXT NOT NULL DEFAULT '',
    insight_id TEXT,
    payload JSONB
);
CREATE INDEX IF NOT EXISTS idx_insight_events_ts ON insight_events(ts);
CREATE INDEX IF NOT EXISTS idx_insight_events_event ON insight_events(event);
```

## 回退

若 PG 不可用，事件追加到 **`data/logs/insight_events.jsonl`**（每行 JSON）。

## 示例查询

```sql
-- 点击证据次数
SELECT COUNT(*) FROM insight_events WHERE event = 'click_reference';

-- 冲突区切换（分组间）
SELECT COUNT(*) FROM insight_events WHERE event = 'switch_conflict_group';

-- 停留（按 section）
SELECT payload->>'section' AS section, COUNT(*) FROM insight_events
WHERE event = 'dwell_time' GROUP BY 1;
```

## 事件名（见前端 `GroundedInsightPanel`）

| event | 说明 |
|-------|------|
| `click_reference` | 点击 `[n]`，`payload.position`: summary \| group |
| `hover_tooltip` | 悬停引用，`payload.features` |
| `switch_conflict_group` | 激活的 ref 在 support_groups 间切换 |
| `view_support_group` | 某分组行首次进入视图 |
| `dwell_time` | `payload.section`, `duration_ms` |
| `user_question` | 预留（如后续接输入框） |
| `query_submitted` | 提交问题；`payload.query_len`, `has_doc_scope`, `doc_id` |
| `answer_generated` | LLM 返回答案；`payload.source`（`rag`/`facts`）, `answer_len`, `contains_not_found`, `semantic_expansion_used` |
| `follow_up_query` | 同一 session 30 秒内再次提问；`payload.prev_query_len`, `new_query_len` |

## 架构更新（Agentic Retrieval）

当前系统主路径已升级为 **rag(raw chunks) + llm**，不再以 selection/summary 作为主判断链路。

- 主分析口径：`source = rag`
- 核心行为指标：`click_reference`、`dwell_time`、`query_submitted`
- 说明：selection/summary 路径仅保留为历史兼容或降级分支，不作为主要产品判断依据

## 产品判断 SQL（v0：doc scoped vs global）

目标：比较两种模式谁更“可理解”（是否更容易进入证据，而非回答准确率）。

### 0) 分组口径

```sql
CASE WHEN doc_id = '__search__' THEN 'global' ELSE 'doc_scoped' END AS mode
```

> 说明：当前 `SearchPage` 在未选择文档时写入 `__search__`，选择文档后写实际 `file_name`。

### 1) 证据点击率（每 session）

```sql
SELECT
  CASE WHEN doc_id = '__search__' THEN 'global' ELSE 'doc_scoped' END AS mode,
  COUNT(*) FILTER (WHERE event = 'click_reference') * 1.0
    / NULLIF(COUNT(DISTINCT session_id), 0) AS click_per_session
FROM insight_events
GROUP BY mode
ORDER BY mode;
```

### 2) 冲突探索率（每 session）

```sql
SELECT
  CASE WHEN doc_id = '__search__' THEN 'global' ELSE 'doc_scoped' END AS mode,
  COUNT(*) FILTER (WHERE event = 'switch_conflict_group') * 1.0
    / NULLIF(COUNT(DISTINCT session_id), 0) AS switch_per_session
FROM insight_events
GROUP BY mode
ORDER BY mode;
```

### 3) 停留但不点击（负信号）

```sql
WITH per_session AS (
  SELECT
    session_id,
    MAX(CASE WHEN doc_id = '__search__' THEN 'global' ELSE 'doc_scoped' END) AS mode,
    SUM(
      CASE
        WHEN event = 'dwell_time'
         AND payload->>'section' = 'conflict'
         AND (payload->>'duration_ms') ~ '^[0-9]+$'
        THEN (payload->>'duration_ms')::bigint
        ELSE 0
      END
    ) AS conflict_dwell_ms,
    COUNT(*) FILTER (WHERE event = 'click_reference') AS click_cnt
  FROM insight_events
  GROUP BY session_id
)
SELECT
  mode,
  COUNT(*) FILTER (WHERE conflict_dwell_ms > 5000 AND click_cnt = 0) AS stuck_sessions,
  COUNT(*) AS total_sessions,
  COUNT(*) FILTER (WHERE conflict_dwell_ms > 5000 AND click_cnt = 0) * 1.0
    / NULLIF(COUNT(*), 0) AS stuck_ratio
FROM per_session
GROUP BY mode
ORDER BY mode;
```

### 4) Evidence Engagement Score（EES）

```sql
WITH session_mode AS (
  SELECT
    session_id,
    CASE WHEN doc_id = '__search__' THEN 'global' ELSE 'doc_scoped' END AS mode,
    COUNT(*) AS event_count,
    COUNT(*) FILTER (WHERE event = 'click_reference') AS click_count
  FROM insight_events
  GROUP BY session_id, mode
)
SELECT
  mode,
  AVG(click_count * 1.0 / NULLIF(event_count, 0)) AS evidence_engagement_score,
  AVG(event_count) AS avg_events_per_session
FROM session_mode
GROUP BY mode
ORDER BY mode;
```

### 5) 会话事件回放（用于人工判读）

```sql
SELECT
  session_id,
  to_timestamp(ts / 1000.0) AS ts_at,
  CASE WHEN doc_id = '__search__' THEN 'global' ELSE 'doc_scoped' END AS mode,
  event,
  payload
FROM insight_events
WHERE session_id = :session_id
ORDER BY ts ASC;
```

### 6) v3 候选（当前落地形态）

当前 `friction_v3_candidates` 为 JSONL（`data/logs/friction_v3_candidates.jsonl`），不是 PG 表。
若后续要做纯 SQL 聚合，建议先建表并在 controller 里同步写入。

## Agentic Retrieval 验证 SQL（v1）

### 1) `[n]` 点击率（session 口径）

```sql
SELECT
  COUNT(DISTINCT session_id) FILTER (WHERE event='click_reference') * 1.0
  / NULLIF(COUNT(DISTINCT session_id) FILTER (WHERE event='query_submitted'), 0)
  AS click_reference_rate
FROM insight_events;
```

### 2) 追问率（session 口径）

```sql
SELECT
  COUNT(DISTINCT session_id) FILTER (WHERE event='follow_up_query') * 1.0
  / NULLIF(COUNT(DISTINCT session_id) FILTER (WHERE event='query_submitted'), 0)
  AS follow_up_rate
FROM insight_events;
```

### 3) 未命中率（answer 口径）

```sql
SELECT
  COUNT(*) FILTER (WHERE event='answer_generated' AND payload->>'contains_not_found'='true') * 1.0
  / NULLIF(COUNT(*) FILTER (WHERE event='answer_generated'), 0)
  AS not_found_rate
FROM insight_events;
```
