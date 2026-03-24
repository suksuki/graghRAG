# 系统定位与边界（防跑偏原则）

本仓库的**产品内核**是 **Document Intelligence（文档智能）**：把非结构化文档变成可检索、可解释、可复用的理解结果（摘要、关键词、主题、向量块、轻量图结构等）。

---

## 英文表述（对外 / 评审用）

This system is a **Document Intelligence** platform.

- **Graph** is a **supporting structure** for document understanding and retrieval augmentation — not the primary source of truth.
- **No domain-specific schema** is enforced at the product level (no fixed industry ontology).
- **No business entities are hardcoded**; company names in prompts are **few-shot examples** only, not business rules.
- **Extraction is model-driven**; fallback paths are generic (e.g. weak `RELATED_TO` edges) and domain-agnostic.

**Design principle:** stay generalizable across domains and document types (legal, medical, technical, financial, etc.).

**Retrieval principle (hybrid):** **vector recall first**, **graph expansion second** — graph must not become the main entry for answers unless explicitly scoped in a future product mode.

---

## 中文表述（对内）

- **图**：文档理解的**副产物与增强层**，用于扩展上下文与可解释性；**不是**业务系统的唯一主数据入口。
- **向量与 chunk + DI metadata**：面向问答与检索的**主路径**。
- **融合检索**（如 `POST /api/v1/hybrid-search`）：**先向量、后按种子实体扩图**，避免「先图后向量」的产品倒置。
- **Few-shot 里的公司名**（如阿里巴巴、Apple）：仅用于稳定模型输出格式，**不是**内置业务知识。
- **质量控制**（如 `kg_confidence`、查询阈值）：横切能力，**不是**行业规则。

---

## 明确避免的方向

| 倾向 | 说明 |
|------|------|
| Graph-first 问答 | 以图为先、向量为补，易滑向「行业知识图谱项目」 |
| 强行固定关系类型体系 | 如强制 `IS_SUPPLIER_OF` 等行业边，需独立产品决策 |
| 代码里的领域规则 | 如 `if "公司" in text: type = Company` |

---

## 自检问题

> 换一批完全不同领域的文档，同一套摄取与检索逻辑是否仍能工作？

若答案为「是」，则仍落在 **Document Intelligence + Graph 增强** 的正道上。
