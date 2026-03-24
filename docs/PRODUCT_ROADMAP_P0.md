# 产品化 P0 Roadmap（中小企业知识库）

## 目标

将当前 GraphRAG 系统升级为：**可用、好用的企业知识库产品**。

核心能力：

- 文档可见（不是黑盒）
- 知识可浏览（不是只能问）
- 信息可检索（搜索 + 问答）
- 关系可理解（Graph）

---

## P0 功能模块（必须完成）

### 1. 文档中心（Document Center）

#### 后端

- [x] 新增 API: `GET /api/docs`
- [x] 新增 API: `GET /api/docs/{id}`

#### 数据

- [x] `doc_id`
- [x] `name`
- [x] `summary`（复用现有 summary）
- [x] `entities`（从 graph 聚合）
- [x] `tags`（可从 graph 推断）

#### 实现约束（第一阶段）

- 不新增数据库表
- 从 Neo4j + 向量 metadata 聚合

#### 前端

- [x] 新建页面：Documents
- [x] 文档卡片组件：文件名、summary、tags
- [x] 点击进入详情页

---

### 2. 文档详情页（Document Detail）

#### 后端

- [x] 聚合：summary、entities、relations（可选）

#### 前端

- [x] 页面：Document Detail
- [x] 展示：Summary、Entities、Related Knowledge、推荐问题（调用 suggestions）

---

### 3. 搜索系统（Search）

#### 后端

- [x] 新增 API: `GET /api/search?q=`
- [x] 实现：使用 `VectorEngine` retriever，返回 top chunks

#### 返回结构（示例）

```json
{
  "results": [
    {
      "doc": "test.pdf",
      "snippet": "..."
    }
  ]
}
```

#### 前端

- [x] 新建页面：Search
- [x] 输入框 + 结果列表
- [x] 点击跳转文档详情

---

### 4. 实体页（Entity Page）

#### 后端

- [x] 新增 API: `GET /api/entity/{name}`

#### 返回结构（示例）

```json
{
  "entity": "Transwarp",
  "products": [],
  "domains": [],
  "documents": []
}
```

#### 前端

- [x] 页面：Entity Detail
- [x] 展示：产品、行业、相关文档、推荐问题

---

### 5. 推荐系统扩展

#### 后端

- [x] 扩展 `/graph/suggestions`（或等价 API）：支持 `entity`、支持 `doc_id`

#### 前端

- [x] 文档页展示推荐问题
- [x] 实体页展示推荐问题

---

### 6. Insight（Key Insight）

#### 后端

- [x] 基于 graph summary 生成 insight（复用现有能力）

#### 前端

- [x] 展示：Key Insight

---

## 技术约束（必须遵守）

1. **不改核心** `QueryPipeline`：Graph-first、precompute、language guard 保持。
2. **统一 API 结构**：新增接口走 `api/schemas.py` + `api/controllers/` + `api/routes/`（见项目 MVC 约定）。
3. **单一数据源**：Graph（Neo4j）为结构核心；Vector 仅用于检索与片段。

---

## 开发约束（给实现者）

1. 不要修改 `QueryPipeline`、`GraphEngine` 核心逻辑（除非经评审的显式重构）。
2. 新能力优先复用现有 graph / vector / summary。
3. API 统一走 controllers + routes + schemas。
4. 文档元数据第一阶段从 graph + metadata 聚合，不新建表。

---

## 实施顺序

### 第一阶段（优先）

- [x] 文档中心
- [x] 搜索
- [x] 文档详情

### 第二阶段

- [x] 实体页
- [x] 推荐扩展

### 第三阶段

- [x] Insight
- [ ] Graph UI 产品化优化

---

## 验收标准

### 功能层

用户可以：上传文档 → 浏览文档 → 搜索内容 → 查看关系。

### 体验层

- 知识不黑盒（可浏览、可检索）
- 多语言一致（语言守卫与缓存策略保持）
- 错误可解释（沿用现有错误体系）

---

## 一句话目标

从「AI 系统」→「知识产品」：普通员工能 **不费脑** 用起来。
