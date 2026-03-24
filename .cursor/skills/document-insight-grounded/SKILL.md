---
name: document-insight-grounded
description: >
  Behavioral contract for DI-first grounded document insight: evidence-bound summaries,
  [n] citations aligned with supporting_chunks.ref_index, graph as auxiliary only.
  Use when changing POST /api/v1/insights/document, document_insight_service, Insight UI
  (GroundedInsightPanel / parseSummaryRefs), or prompts that generate cited summaries.
---

# Document Insight — Grounded（有据洞察）行为规范

## 本 Skill 的定位（必读）

- **是**：行为与契约约束层——防止 Insight 退化成「自由生成」或 Graph-first。
- **不是**：UI 状态同步工具、也不是「替 UI 接 API」的清单；前后端接线仍靠正常开发与测试完成。
- **不是**：图谱抽取或 GraphRAG 问答主路径规范（那是 `graphrag-query` / `graphrag-graph`）。

### 冲突与优先级（Source of truth）

```text
If conflicts occur:
- The running API / service implementation and OpenAPI-visible schemas are the source of truth.
- This skill describes expected behavior and review criteria; it does not override code at runtime.
- Resolve drift by: (1) fixing code to match the contract, or (2) updating this skill after an intentional product change (same PR).
```

避免有人试图「用 Skill 覆盖代码行为」或把 Markdown 当作可执行规范。

---

## 能力边界（产品语义）

```text
Retrieval  →  supporting_chunks（主证据）
Reasoning  →  LLM summary（严格受限于 SOURCES）
Grounding  →  [n] ↔ ref_index ↔ snippet
Graph      →  key_relations（辅助信号，不可替代 chunk）
```

---

## API 契约：`POST /api/v1/insights/document`

### 输入（概念）

| 字段 | 说明 |
|------|------|
| `query` | 用户问题或关注点 |
| `top_k` | 参与 grounding 的向量片段上限 |
| `doc_id` | 可选；收窄到单文件 `metadata.file_name` |
| `include_graph_relations` | 可选；为 false 时不查 Neo4j 关系 |

### 输出（必须保持的语义）

| 字段 | 约束 |
|------|------|
| `summary` | 有 `supporting_chunks` 时，须通过 prompt 要求句末使用 **`[1]`、`[2]`** 等，且仅引用已提供的编号。 |
| `supporting_chunks` | 每项必须有 **`ref_index`**（从 1 递增），与 prompt 里 SOURCES 编号一致。 |
| `key_relations` | **辅助**；可含 `kg_source` / `kg_confidence`；不得被当作可脱离片段独立采信的结论。 |
| `insufficient_evidence` | 无可用片段时为 `true`，且**不得**为凑答案调用 LLM 生成虚构摘要。 |

实现参考：`core/document_insight_service.py`、`api/schemas.py`（`DocumentInsightResponse`、`DocRelationItem`）、`api/controllers/document_insight_controller.py`。

---

## 强约束规则（修改代码时不得破坏）

1. **无 chunk → 不调 LLM**：没有合格 `supporting_chunks` 时，返回固定说明文案（多语言），`insufficient_evidence: true`。
2. **主证据只能是向量片段正文**：prompt 中 SOURCES 仅来自本轮检索到的 chunk；禁止把 `key_relations` 三元组写进「可引用证据列表」冒充主证据。
3. **引用号与 ref_index 一一对应**：`[n]` 仅指向 `ref_index === n` 的 chunk；新增/删减 chunk 时同步重算编号与 prompt 块。
4. **图关系为辅助**：关系可进入响应供 UI 展示上下文，但 prompt 须明确「不得用关系替代 SOURCES 中的事实」。
5. **禁止静默降级**：不要把「无证据」改成「调用 LLM 自由回答」；不要在没有 SOURCES 时打开生成。

---

## Prompt / LLM 侧（摘要形态示例）

模型输出应接近（语言随 `x-lang` / `lang_final` 变化，结构一致）：

```text
Alibaba provides e-commerce and cloud services [1][3].
Its headquarters is in Hangzhou [2].
```

- 允许一句多引用 `[1][3]`。
- 不允许无编号的主观扩展句；若无法从 SOURCES 支持，应省略或明确「语料未提及」。

---

## 前端 UI 协议（与后端对齐）

- 解析：`summary` 中的 **`\[(\d+)\]`** → 与 `supporting_chunks[].ref_index` 映射（勿假设数组下标 `n-1` 等于 ref，以 **`ref_index` 为准**）。
- 交互建议：hover / click `[n]` ↔ 高亮对应来源；单独提供「打开文档」跳转 `file_name`。
- 实现参考：`apps/src/utils/parseSummaryRefs.js`、`apps/src/components/GroundedInsightPanel.jsx`、`apps/src/hooks/useDocumentInsight.js`。

---

## 与 Corpus 洞察（`/insights/corpus`）的关系

- **Corpus**：聚合多文档 **`di_*` metadata**，与 Neo4j 节点数无必然关系。
- **Document Insight（本 Skill）**：单次查询 + **向量片段 grounding**，不依赖 `di_*` 聚合是否存在。
- 二者不可混用契约；不要在文档或 UI 文案中暗示「有图就一定有 Corpus 洞察」。

---

## 反模式（明确禁止）

| 反模式 | 原因 |
|--------|------|
| 用 Skill 代替「把 UI 接到正确 API」 | Skill 不执行接线；接线是工程任务。 |
| 以 `key_relations` 为主证据写摘要 | Graph-first / 幻觉风险，违背 DI-first。 |
| 无 `supporting_chunks` 仍调用 LLM 写 summary | 破坏 grounded 定义。 |
| 前端只渲染纯文本 summary、忽略 `ref_index` | 破坏可解释性与产品承诺。 |
| 另起接口把「检索 + 长生成」混在单一端点里 | 不利于缓存、测试与责任边界；保持检索与表达分层。 |

---

## 相关文档与技能

- 产品边界：`docs/DOCUMENT_INTELLIGENCE_POSITIONING.md`
- HTTP 说明：`docs/API_REFERENCE.md`（§12 单请求文档洞察）
- 前端大图：`graphrag-frontend` skill
- 后端 MVC：`graphrag-mvc` skill

---

## 变更检查清单（PR 自检）

- [ ] `document_insight_service` 仍在无片段时跳过 LLM。
- [ ] `supporting_chunks` 仍带 `ref_index`，且与 prompt 编号一致。
- [ ] `key_relations` 仍标注为辅助；schema 描述未弱化。
- [ ] 前端若改摘要渲染，仍按 `ref_index` 映射，而非纯数组顺序。
- [ ] 未引入「仅用图关系生成摘要」的代码路径。
