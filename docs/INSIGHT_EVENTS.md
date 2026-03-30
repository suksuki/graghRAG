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
| `select_doc_scope` | 选择某个文档作为范围；`payload.doc_id` |
| `query_with_doc_scope` | 在文档范围内发起查询；`payload.query_len` |
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

## 系统验证期每日指标 SQL（Observation Mode）

### 1) click_rate（证据点击率）

```sql
SELECT
  COUNT(*) FILTER (WHERE event = 'click_reference') * 1.0
  / NULLIF(COUNT(*) FILTER (WHERE event = 'query_submitted'), 0) AS click_rate
FROM insight_events;
```

### 2) follow_up_rate（追问率，30 秒窗口）

```sql
WITH q AS (
  SELECT session_id, to_timestamp(ts / 1000.0) AS created_at
  FROM insight_events
  WHERE event = 'query_submitted'
),
pairs AS (
  SELECT q1.session_id
  FROM q q1
  JOIN q q2
    ON q1.session_id = q2.session_id
   AND q2.created_at > q1.created_at
   AND q2.created_at <= q1.created_at + interval '30 seconds'
)
SELECT
  COUNT(DISTINCT session_id) * 1.0
  / NULLIF((SELECT COUNT(DISTINCT session_id) FROM q), 0) AS follow_up_rate
FROM pairs;
```

### 3) not_found_rate（未命中率）

```sql
SELECT
  COUNT(*) FILTER (
    WHERE event = 'answer_generated'
      AND payload->>'contains_not_found' = 'true'
  ) * 1.0
  / NULLIF(COUNT(*) FILTER (WHERE event = 'answer_generated'), 0) AS not_found_rate
FROM insight_events;
```

### 4) semantic_expansion_rate（语义扩展率）

```sql
SELECT
  COUNT(*) FILTER (
    WHERE event = 'answer_generated'
      AND payload->>'semantic_expansion_used' = 'true'
  ) * 1.0
  / NULLIF(COUNT(*) FILTER (WHERE event = 'answer_generated'), 0) AS semantic_expansion_rate
FROM insight_events;
```

### 5) doc_scope_selection_to_query_rate（选择后转化率）

```sql
WITH selections AS (
  SELECT
    session_id,
    doc_id,
    ts,
    LEAD(ts) OVER (PARTITION BY session_id ORDER BY ts ASC) AS next_select_ts
  FROM insight_events
  WHERE event = 'select_doc_scope'
),
converted_selections AS (
  SELECT COUNT(*) AS converted_count
  FROM selections s
  WHERE EXISTS (
    SELECT 1
    FROM insight_events q
    WHERE q.event = 'query_with_doc_scope'
      AND q.session_id = s.session_id
      AND COALESCE(q.doc_id, '') = COALESCE(s.doc_id, '')
      AND q.ts > s.ts
      AND (s.next_select_ts IS NULL OR q.ts < s.next_select_ts)
  )
)
SELECT
  (SELECT converted_count * 1.0 FROM converted_selections)
  / NULLIF(COUNT(*) FILTER (WHERE event = 'select_doc_scope'), 0)
  AS doc_scope_selection_to_query_rate
FROM insight_events;
```

### 6) scoped_vs_global_query_window_click_rate（查询窗口口径）

```sql
WITH query_events AS (
  SELECT
    session_id,
    ts,
    CASE
      WHEN event = 'query_with_doc_scope' THEN true
      WHEN event = 'query_submitted' AND (payload->>'has_doc_scope') = 'true' THEN true
      ELSE false
    END AS is_scoped
  FROM insight_events
  WHERE event IN ('query_submitted', 'query_with_doc_scope')
),
queries AS (
  SELECT
    session_id,
    ts AS query_ts,
    BOOL_OR(is_scoped) AS is_scoped,
    LEAD(ts) OVER (PARTITION BY session_id ORDER BY ts ASC) AS next_query_ts
  FROM query_events
  GROUP BY session_id, ts
),
attributed AS (
  SELECT
    q.session_id,
    q.query_ts,
    q.is_scoped,
    EXISTS (
      SELECT 1
      FROM insight_events c
      WHERE c.event = 'click_reference'
        AND c.session_id = q.session_id
        AND c.ts > q.query_ts
        AND (q.next_query_ts IS NULL OR c.ts < q.next_query_ts)
    ) AS clicked
  FROM queries q
)
SELECT
  COUNT(*) FILTER (WHERE is_scoped AND clicked) * 1.0
    / NULLIF(COUNT(*) FILTER (WHERE is_scoped), 0) AS scoped_query_window_click_rate,
  COUNT(*) FILTER (WHERE NOT is_scoped AND clicked) * 1.0
    / NULLIF(COUNT(*) FILTER (WHERE NOT is_scoped), 0) AS global_query_window_click_rate
FROM attributed;
```

### 补充参考口径 A) 追问率（session 口径）

```sql
SELECT
  COUNT(DISTINCT session_id) FILTER (WHERE event='follow_up_query') * 1.0
  / NULLIF(COUNT(DISTINCT session_id) FILTER (WHERE event='query_submitted'), 0)
  AS follow_up_rate
FROM insight_events;
```

### 补充参考口径 B) 未命中率（answer 口径）

```sql
SELECT
  COUNT(*) FILTER (WHERE event='answer_generated' AND payload->>'contains_not_found'='true') * 1.0
  / NULLIF(COUNT(*) FILTER (WHERE event='answer_generated'), 0)
  AS not_found_rate
FROM insight_events;
```
