# Agentic Retrieval Architecture (v1)

## 1. 核心原则

- LLM 是系统核心：负责问题理解、检索意图判断、基于证据的最终回答。
- RAG 是工具层：负责从文档中缩小范围并提供原始材料。
- 代码只负责组织数据与安全边界，不负责语言语义判断。
- 系统原则：**RAG 缩小范围，LLM 做最终判断**。

## 2. 当前系统架构

```text
User Query
  -> LLM (query planning: intent/focus)
  -> Retrieval (doc-scoped RAG)
  -> LLM (grounded answer on raw chunks)
  -> Evidence UI
```

## 3. 已废弃路径（Deprecated）

以下路径已降级或弃用，不再作为主路径：

- summary-first 路径
- selection / candidate 路径
- regex / keyword 语义判断
- 硬编码翻译 / 映射逻辑

原因：以上方式在代码层模拟语言理解，复杂度高且稳定性差，不符合 LLM-first 原则。

## 4. 当前主流程（`run_document_insight`）

1. 使用 LLM 解析 query（`need_retrieval` / `focus` / `intent`）。
2. 使用 `query + focus` 做 doc-scoped 检索，获取相关 chunk。
3. 将原文 chunk 直接传给 LLM 生成回答。
4. 输出统一结构：`answer`、`source`、`supporting_chunks`（`summary` 仅兼容保留），供 UI 展示证据链路。

约束：

- 不做翻译中间层
- 不做候选构造中间层
- 不做 regex 语义分类

## 5. Prompt 设计原则

- 回答必须基于提供的原文 chunk。
- 明确禁止 hallucination（编造文档外事实）。
- 问题无证据时必须显式回答“未提及”或同等语义。

## 6. 适用场景

- PPT、流程型文档、非线性文档（摘要路径容易丢结构）。
- 中小企业知识库（文档格式混杂，问题类型跨度大）。
- 本地 LLM 部署场景（可接受较高 token 使用以换取语义稳定性）。

## 7. 后续演进方向（文档规划）

仅记录方向，不在当前版本实现：

- 更强 query planning（更稳定的 intent/focus）
- 可选 multi-step retrieval（复杂问题分步取证）
- tool-based retrieval（按任务调用不同检索工具）

---

当前版本定位：**LLM-first Document Intelligence System**。
