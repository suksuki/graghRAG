# Document Intelligence 设计分层纪律

> **北极星约束**：指导文档智能（有据摘要、证据 UI、后续能力）的扩展方式，避免「局部过拟合」与「模型断言替代证据」。
>
> 与 [系统定位与边界](./DOCUMENT_INTELLIGENCE_POSITIONING.md) 配合阅读。

---

## 核心哲学（README 级表述）

本系统**优先展示证据结构**，而非不可验证的「模型结论」。  
所有解释与判断须基于**可追溯的数据**；禁止用**不可解释的概率或分数**冒充「可信度」。

---

## 分层定义

### 1. Evidence（证据层）— 当前目标：已完成

**目标**：让结论**可追溯、可验证**。

必须满足：

- 每个结论都有来源（如 `[n]`）
- 可点击跳转（证据导航）
- 可查看上下文（snippet / 文档定位）
- 不依赖模型「口头解释」替代原始证据

禁止：

- 无来源结论
- 仅凭模型生成句当作「已证实」事实

---

### 2. Reasoning（轻解释层）— 当前状态：已封板

**目标**：帮助用户理解**证据之间的关系**，而非引入新的推理链或第二套生成内容。

约束：

- 只使用**已有信号**（如 co-citation、rank）
- 表达为**一行**自然语言（必要时按状态切换文案，不叠句）
- **不**增加新 UI 层级（不新增卡片 / 模块为主入口）
- **不**引入仅服务于展示的新数据结构

禁止：

- 多段说教式解释
- 复杂推理链可视化（除非进入 Decision 并单独评审）
- 为「看起来更智能」而新增组件 / 强视觉强调

---

### 3. Decision（判断层）— 未来：待定义与实现

**目标**：系统对信息做**判断**（而不仅是陈列），且判断依据仍可追溯到证据或明确规则。

允许范围（示例）：

- 冲突识别（A vs B）
- **v1 已实现（仅标记）**：`supporting_chunks` 间**关键词子串对**启发式检出（`POST /api/v1/insights/document` 的 `decision.conflicts`），只提示用户对照来源，**不裁决对错、不给分**
- **v2 已实现（仅结构）**：当 `conflicts` 非空时，附加 `decision.support_groups`（按 snippet 关键词粗分桶的 `ref_index` 列表），**不合并为「哪边赢」、不给置信度**
- 多证据一致性归纳（在**有信号**的前提下）
- 风险 / 注意点提示
- 实体级归纳结论（依赖聚合结果，非单句模型断言）

**前置条件（须至少满足一项再启动该层产品化）**：

- 存在可计算的**冲突证据**
- 存在可展示的**多路径证据链**
- 存在**实体级聚合**结果
- 存在**用户行为信号**（点击、偏好、显式反馈等）

#### Decision 层禁止事项

- 在**无真实信号**时输出「可信度 87%」等伪概率
- 用模型 logits / 概率**替代**证据结构叙事
- 将系统从「证据驱动」滑成「模型断言驱动」

**原则**：Decision 是**判断能力**（规则 + 数据 + 可选模型），不是「再多一块说明 UI」。

---

## 团队使用守则：新功能三问

接到需求或方案时，先对齐：

1. **属于哪一层？** Evidence / Reasoning / Decision？
2. **是否违反该层约束？**（例如：Reasoning 是否变多段？Decision 是否无信号？）
3. **是否破坏当前 UI 哲学？** 轻、可导航、不打扰。

---

## 版本与维护

- 本文档随产品阶段更新；**封板**状态（如 Reasoning）变更时须在 PR 中说明理由。
- 实现参考：前端有据摘要与 tooltip 见 `apps/src/components/GroundedInsightPanel.jsx`；API 见 `POST /api/v1/insights/document`。

---

## 执行约束

凡涉及以下改动的 PR，**视为须显式对齐本文档**：

- Insight 生成（单文档 / 语料级）
- 证据展示（引用、`[n]`、tooltip、来源列表等）
- 解释 / 推理类文案或 UI（含 Reasoning 层任何变更）
- 任何「可信度、可靠度、置信度、判断结论」等面向用户的能力或展示

**必须在 PR 描述中：**

1. **引用本文件**（路径或链接：`docs/DOCUMENT_INTELLIGENCE_DESIGN_DISCIPLINE.md`）
2. **标注层级**：说明改动属于 **Evidence / Reasoning / Decision** 哪一层（或跨层，并分项说明）
3. **自检声明**：确认未违反本文档中该层的约束与禁止项

未满足上述条件的 PR **视为不完整**，合并前须补全。

---

## Enforcement (English, for PR descriptions)

All changes that touch any of the following **must** align with this document:

- Insight generation (per-document or corpus-level)
- Evidence display (citations, `[n]`, tooltips, source lists, etc.)
- Reasoning / explanation copy or UI (including any Reasoning-layer change)
- Any user-facing “confidence”, “reliability”, or “decision” capability

**PR description must:**

1. **Reference this file** (`docs/DOCUMENT_INTELLIGENCE_DESIGN_DISCIPLINE.md`)
2. **State the layer**: Evidence / Reasoning / Decision (or cross-layer, with a short breakdown)
3. **Confirm compliance**: explicitly note that the change does not violate the constraints and prohibitions here

PRs missing the above are **considered incomplete** until updated.
