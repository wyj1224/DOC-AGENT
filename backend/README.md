# DOC AGENT Backend

后端基于 FastAPI，负责用户认证、会话记忆、Agent 编排、Word 一致性与完整性校验、Excel 标准库和通用知识库 RAG。

详细源码职责见根目录 [agent.md](../agent.md)。本文只保留后端运行、配置、数据库、接口和命令速查。

## 1. 运行组件

| 组件 | 用途 |
| --- | --- |
| FastAPI | HTTP API 与 SSE 响应 |
| PostgreSQL | 用户、会话、标准库、Word 解析结果、问题和运行记录 |
| Milvus Lite | 强条向量集合与通用知识库双向量集合 |
| DeepSeek | Agent Planner、最终回答和 RAG 引用回答 |
| 千问 Embedding | 通用知识库稠密向量 |
| 千问视觉模型 | 从 PDF 页面识别公告/规则/无强条声明，并读取像素筛选后的黑体候选行条号 |
| jieba | 中文关键词分词与稀疏向量 |
| LlamaParse | 通用知识文件和强条正文 OCR 转 Markdown |
| PyMuPDF | 将 PDF 物理页面渲染为视觉模型输入图片 |
| python-docx | Word 本地解析、精确 run 写回和修订副本输出 |

PostgreSQL 通过 Docker 启动。Milvus Lite 使用本地文件，不需要额外启动 Milvus 服务。

## 2. 环境要求

- Python 3.11
- Docker Desktop
- 可访问 DeepSeek、阿里百炼和 LlamaParse API

建议使用独立环境：

```bash
conda create -n clause-agent python=3.11 -y
conda activate clause-agent
python -m pip install --upgrade pip setuptools wheel
```

## 3. 环境变量

```bash
cd backend
cp .env.example .env
```

编辑 `.env`：

| 变量 | 用途 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL SQLAlchemy 连接串 |
| `JWT_SECRET` | JWT 签名密钥，必须替换示例值 |
| `JWT_EXPIRE_MINUTES` | Token 有效时间 |
| `DEEPSEEK_API_KEY` | Planner 和回答模型密钥 |
| `DEEPSEEK_BASE_URL` | DeepSeek OpenAI Compatible 地址 |
| `DEEPSEEK_MODEL` | Agent 使用的模型名 |
| `QWEN_API_KEY` | 千问 Embedding 密钥 |
| `QWEN_BASE_URL` | 千问 OpenAI Compatible 地址 |
| `QWEN_EMBEDDING_MODEL` | Embedding 模型名 |
| `DASHSCOPE_API_KEY` | 百炼视觉模型密钥；未配置时可回退读取 `QWEN_API_KEY` |
| `QWEN_VISION_BASE_URL` | 百炼或工作空间 OpenAI Compatible 地址 |
| `QWEN_VISION_MODEL` | PDF 视觉识别模型，当前默认 `qwen3.7-plus` |
| `LLAMA_CLOUD_API_KEY` | LlamaParse 密钥 |
| `APP_MILVUS_URI` | Milvus Lite 数据文件路径 |
| `MILVUS_COLLECTION` | 强条向量集合名 |
| `KNOWLEDGE_MILVUS_COLLECTION` | 通用知识库集合名 |

`.env` 含真实密钥，不要提交。

## 4. 安装与启动

安装依赖：

```bash
cd backend
python -m pip install -r requirements.txt
```

启动 PostgreSQL：

```bash
docker compose up -d postgres
```

初始化数据库：

```bash
python -m app.cli.init_db
```

启动 API：

```bash
python -m uvicorn app.main:app --reload
```

访问地址：

- 健康检查：`http://127.0.0.1:8000/health`
- Swagger：`http://127.0.0.1:8000/docs`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`

## 5. 数据库表

| 表 | 内容 |
| --- | --- |
| `users` | 用户名、显示名和密码哈希 |
| `agent_sessions` | 用户会话、消息 JSONB、摘要和最近文档/运行 ID |
| `check_runs` | Agent 工具计划、工具结果、回答、耗时和运行状态 |
| `word_edit_runs` | 每次 Word 修改请求的唯一任务记录；保存按 cycle 累积的 `changes`、LLM/工具决策轨迹、执行状态、最新副本和复检关联 |
| `clause_extraction_runs` | PDF 强条 Agent 任务；保存文件指纹、视觉/OCR 证据、`result_json`、状态和决策轨迹 |
| `mandatory_clauses` | Excel 强制性条文记录 |
| `standard_validity_records` | Excel 新旧标准替代关系 |
| `knowledge_documents` | RAG 文件、解析状态、页数和切块数 |
| `word_documents` | 上传的待检 Word 文档；修订副本以唯一的 `edit_run_id + edit_cycle` 支持幂等解析与恢复 |
| `word_references` | Word 标准号、标准名、条号和上下文 |
| `word_sections` | Word 标题和标题之间的正文 |
| `word_templates` | 模板文件、年份、类型和标题数 |
| `word_template_headings` | 模板标题列表 |
| `word_template_key_sections` | 三个关键章节的模板正文、子章节编号和文本块快照 |
| `check_issues` | 一致性和完整性问题 |

`app.db.database.init_db()` 除 `create_all` 外，还包含开发阶段的兼容性字段和索引补齐。新增正式迁移需求后应改用 Alembic。

## 6. 认证

公开接口：

```text
GET  /health
POST /auth/register
POST /auth/login
```

登录成功后，业务请求需要：

```http
Authorization: Bearer <access_token>
```

当前用户：

```text
GET /auth/me
```

会话和 Agent 运行记录会按当前用户过滤。知识库、模板和 Excel 标准库当前作为共享资料库使用。

## 7. 主要接口

### Agent 与会话

```text
POST   /agent/check
POST   /agent/check/stream
GET    /agent/sessions
GET    /agent/sessions/{session_id}
DELETE /agent/sessions/{session_id}
GET    /agent/runs
GET    /agent/runs/{run_id}
DELETE /agent/runs/{run_id}
```

`POST /agent/check` 使用 `multipart/form-data`：

```text
message: 用户问题
document_id: 已上传文档 ID，可选
session_id: 当前会话 ID，可选
publish_date: YYYY-MM-DD，可选
file: Word 文件，可选
```

`POST /agent/check/stream` 返回 SSE 事件：`status`、`result`、`delta`、`done` 或 `error`。当前实现是在后端完成 Agent 运行后，将最终回答按小段输出。

### Word

```text
POST /word/upload
POST /word/check
POST /word/completeness-check
POST /word/fix-consistency
GET  /word/issues
GET  /word/sections
GET  /word/documents/{document_id}/download
```

- `/word/upload` 只接受 `.docx`。
- `/word/check` 执行依据 vs Excel 和正文 vs 依据的一致性检查。
- `/word/completeness-check` 自动匹配模板，检查标题、正文和占位符，并比较三个关键章节的正文及子章节编号；文字相似度低于 95% 报警。
- `/word/fix-consistency` 启动外层 Word Agent Loop：Agent 根据每步 Observation 逐步调用 `inspect`、`prepare`、`apply` 和 `verify`，工具仅修改一致性检查中的警告和高风险问题，并生成副本。
- `/word/documents/{document_id}/download` 下载当前用户的原文或修订副本。

Word 修订不再由一个固定顺序、固定轮数的内部函数编排。外层 Agent 工作流在一次请求内只创建一条 `WordEditRun`，并在同一条记录的 `changes` 中累积各 cycle 的精确修改。LLM 只选择下一动作和可修问题 ID；`before/after`、`fix_data`、`locator` 和 `span` 始终由确定性服务构造和校验。`max_steps` 与 `max_cycles` 是异常循环的安全预算，不代表预设两轮或其他固定流程。

### Excel 标准库

```text
POST /excel/ingest
GET  /excel/clauses
GET  /excel/standard-validity
```

`/excel/ingest` 使用 `multipart/form-data`：

```text
file: Excel 文件
sheet: 强条
replace: true
```

### Word 模板库

```text
POST   /templates/upload
GET    /templates
GET    /templates/{template_id}
DELETE /templates/{template_id}
```

上传接口字段为 `files`，支持一次选择一个或多个 `.docx`。年份和 `700M/室内/室外` 类型从文件名自动识别。

### 通用知识库

```text
POST   /knowledge/documents
GET    /knowledge/documents
DELETE /knowledge/documents/{document_id}
POST   /knowledge/query
```

`/knowledge/documents` 的 `files` 字段支持多文件上传。入库流程：

```text
文件 -> LlamaParse Markdown -> 约 700 字切块
     -> jieba 稀疏向量 + 千问稠密向量
     -> Milvus knowledge_chunks
```

`/knowledge/query` 使用：

```text
question: 问题
limit: 5
```

混合检索权重固定为关键词 `0.6`、向量 `0.4`。返回值包含回答、来源文件、页码、原文切块、排名和混合得分。

## 8. Excel 命令行工具

查看工作簿结构：

```bash
python -m app.cli.inspect_excel "../强制性条文整理20260507.xlsx"
```

预览强条切块，不写数据库：

```bash
python -m app.cli.ingest_excel "../强制性条文整理20260507.xlsx" \
  --preview-only \
  --preview-limit 20 \
  --export-chunks data/chunks_preview.jsonl
```

导入 PostgreSQL：

```bash
python -m app.cli.ingest_excel_pg "../强制性条文整理20260507.xlsx" --replace
```

`--replace` 会替换已有 Excel 标准库记录，适合开发和重新导入。

强条向量检索：

```bash
python -m app.cli.search "通信局站应采用联合接地方式"
```

## 9. RAG 冒烟评测

当前样例位于 `data/rag_eval/`。先将 `smoke_knowledge.md` 上传知识库，再执行：

```bash
python -m app.cli.eval_rag data/rag_eval/questions.example.jsonl --top-k 5
```

脚本当前判断：

- 目标来源文件是否进入 Top K。
- 预期关键词是否出现在召回文本中。
- 汇总检索通过率。

这只是评测程序的冒烟验证。正式 RAG 评测集、Recall@K、MRR、引用正确率和答案要点覆盖率仍是下一阶段工作。

## 10. 开发数据说明

- `data/uploads/`：用户上传原文件。
- `data/milvus.db`：Milvus Lite 数据。
- `data/*preview.jsonl`：解析预览。
- `__pycache__/`：Python 缓存。

这些文件不是核心源码。清理数据库或上传文件前，应先确认是否需要保留现有测试数据。

## 11. 当前后端边界

- Agent 已支持检查、查询、会话记忆、运行 Trace 和 Word 副本自动修订；修订由外层 Agent Loop 根据实时 Observation 选择细粒度工具，并由单条 `WordEditRun.changes` 保存跨 cycle 记忆。
- 会话/运行记录已按用户隔离；共享资料库是当前产品选择。
- 部分 Word 直接查询接口仍需要补齐严格的所有权校验。
- 目前使用启动时兼容性建表逻辑，生产环境应引入正式数据库迁移。
- 前端流式展示已可用，但当前不是模型 Token 原生流式调用。
