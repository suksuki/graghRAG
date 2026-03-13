# 📘 SME GraphRAG Platform - User Manual (Trilingual)
# 🔍 企业级知识图谱检索平台使用手册
# 📗 SME GraphRAG 플랫폼 사용자 매뉴얼

---

## 1. System Overview / 系统概况 / 시스템 개요

| Language | Description |
| :--- | :--- |
| **Chinese** | 本系统是专为中小企业设计的 GraphRAG（图谱增强检索）平台。它结合了 **Neo4j 知识图谱**的高逻辑性与 **PostgreSQL 向量数据库**的高语义性，能够精准处理公司文档与照片。 |
| **English** | This platform is a GraphRAG system tailored for SMEs. It combines the logical structure of **Neo4j Knowledge Graphs** with the semantic depth of **PostgreSQL Vector Databases** to accurately process company documents and images. |
| **Korean** | 본 시스템은 중소기업을 위한 GraphRAG(그래프 증강 검색) 플랫폼입니다. **Neo4j 지식 그래프**의 논리적 구조와 **PostgreSQL 벡터 데이터베이스**의 의미론적 깊이를 결합하여 문서와 사진을 정밀하게 처리합니다. |

---

## 2. Core Features / 核心功能 / 핵심 기능

### 📁 Multi-modal Ingestion / 多模态入库 / 멀티모달 데이터 처리
- **CN**: 支持 PDF, Word, Excel, PPT 以及 JPG/PNG 图片（通过 OCR 自动识别内容）。
- **EN**: Supports PDF, Word, Excel, PPT, and JPG/PNG images (Auto-OCR recognized).
- **KO**: PDF, Word, Excel, PPT 및 JPG/PNG 이미지(OCR 자동 인식)를 지원합니다.

### 🧠 Hybrid Search / 混合检索 / 하이브리드 검색
- **CN**: **图谱检索**（理清人际与项目关系）+ **向量检索**（理解深层语义）。
- **EN**: **Graph Search** (mapping relationships) + **Vector Search** (semantic matching).
- **KO**: **그래프 검색**(관계 매핑) + **벡터 검색**(의미론적 매칭)을 결합합니다.

### 🌐 Multi-lingual Support / 三语支持 / 다국어 지원
- **CN**: 界面与检索全面支持中、英、韩三语，利用 Qwen 3.5 强大的语境能力。
- **EN**: Full UI and retrieval support for CN, EN, and KO using Qwen 3.5's reasoning.
- **KO**: Qwen 3.5의 추론 능력을 사용하여 중, 영, 한 3개 국어의 UI와 검색을 지원합니다.

---

## 3. Usage Guide / 使用指南 / 사용 가이드

### 3.1 Accessing the Platform / 访问平台 / 플랫폼 접속
- **Address**: `http://192.168.0.13:3000`
- **API Status**: Verify at `http://192.168.0.13:8000/`

### 3.2 Uploading Files / 上传文件 / 파일 업로드
1. **CN**: 在侧边栏点击“上传文档/照片”，选择文件。
2. **EN**: Click "Upload Docs/Images" in the sidebar and select files.
3. **KO**: 사이드바에서 "문서/사진 업로드"를 클릭하고 파일을 선택합니다.
*Note: Ingestion starts automatically in the background.*

### 3.3 Querying Knowledge / 提问与检索 / 지식 검색
- **CN**: 在对话框输入自然语言问题。例如：“王小明的部门是什么？”或“What are the reimbursement rules?”
- **EN**: Enter questions in natural language. E.g., "What department is Xiao Ming in?"
- **KO**: 자연어로 질문을 입력하세요. 예: "왕소명의 부서는 어디인가요?"

---

## 4. Maintenance / 系统维护 / 시스템 유지보수

### Manual Synchronization / 手动同步 / 수동 동기화
If files are added directly to the disk, run:
```bash
cd /opt/graphrag-platform
.venv/bin/python core/ingestion.py
```

### Server Logs / 查看日志 / 로그 확인
- **Backend API**: `tail -f /opt/graphrag-platform/api.log`
- **Frontend App**: `tail -f /opt/graphrag-platform/apps/frontend.log`

---

## 5. Technical Stack / 技术栈 / 기술 스택
- **LLM**: Qwen 3.5 35B (Local / 192.168.0.10)
- **Framework**: Llama-Index 0.14+
- **Database**: Neo4j (Graph), PostgreSQL + pgvector (Vector)
- **Frontend**: React + Vite + Framer Motion (Premium UI)
- **OCR**: EasyOCR / Unstructured.io

---

## 6. FAQ / 常见问题 / 자주 묻는 질문

**Q: Why is graph analysis slow? / 为什么图谱分析慢？ / 그래프 분석이 왜 느린가요?**
- **A**: The system uses a 35B parameter LLM to extract high-quality entities and relationships, ensuring the "Knowledge Graph" is accurate.
- **CN**: 系统使用 35B 模型进行高质量实体提取，以确保关系图谱的精准度。
- **KO**: 시스템은 정확한 지식 그래프를 위해 35B 모델을 사용하여 고품질 개체와 관계를 추출합니다.

**Q: Can it read handwritten notes? / 能识别手写笔记吗？ / 손글씨 메모도 인식하나요?**
- **A**: Yes, the built-in OCR handles standard handwriting, though clear printed text yields better results.
- **CN**: 支持，内置 OCR 可识别手写，但清晰的打印体效果最佳。
- **KO**: 네, 내장된 OCR로 가능합니다. 인쇄된 텍스트가 가장 정확합니다.

---
**Powered by Antigravity AI Assistant**
**2026-03-10**
