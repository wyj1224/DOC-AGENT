# 灵枢·规鉴 Backend

FastAPI 后端专注两种 Agent 任务：`document_check` 和 `word_edit`。二者共用同一个 Harness、轨迹模型、Evaluator、Retry 和 Experience Memory，业务差异封装在独立 Environment 中。

详细代码地图见根目录 [agent.md](../agent.md)。

## 1. 依赖

- Python 3.11
- PostgreSQL 16
- DeepSeek：ReAct 决策、Reflection 和最终报告
- python-docx：Word 解析与精确写回

本项目不需要 Milvus、Embedding 或中文分词服务。

## 2. 环境变量

```bash
cp .env.example .env
```

关键配置：

```text
DATABASE_URL
VISITOR_COOKIE_SECRET
DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL
DEEPSEEK_MODEL
```

`.env` 含真实密钥，不应提交。

## 3. 启动

```bash
python -m pip install -r requirements.txt
docker compose up -d postgres
python -m app.cli.init_db
python -m uvicorn app.main:app --reload
```

- 健康检查：`GET http://127.0.0.1:8000/health`
- Swagger：`http://127.0.0.1:8000/docs`

## 4. Agent API

```text
POST   /agent/check
POST   /agent/check/stream
GET    /agent/sessions
GET    /agent/sessions/{session_id}
DELETE /agent/sessions/{session_id}
GET    /agent/tasks
GET    /agent/tasks/{task_id}
GET    /agent/experiences
GET    /agent/runs
GET    /agent/runs/{run_id}
DELETE /agent/runs/{run_id}
```

`POST /agent/check` 使用 `multipart/form-data`：

```text
message: 用户要求
document_id: 已解析 Word ID，可选
session_id: 会话 ID，可选
publish_date: YYYY-MM-DD，可选
mode: document_check | word_edit，可选
```

Word 文件统一通过 `POST /word/upload` 上传；Agent 入口只接收解析后的 `document_id`，避免维护两套上传流程。

返回值同时包含：

```text
session_id
task_id
episode_id
attempt_no
status
evaluation
run_id          # 仅文档检查业务记录；兼容旧前端
tool_plan       # 兼容旧前端
tool_results    # 兼容旧前端
answer
```

`GET /agent/tasks/{task_id}` 可查看该 Task 的全部 Episode、Reflection 与 Step 级 action/observation 轨迹。

## 5. 其他 API

Word：

```text
POST /word/upload
POST /word/check
POST /word/completeness-check
POST /word/fix-consistency
GET  /word/issues
GET  /word/sections
GET  /word/documents/{document_id}/download
```

Excel 标准库：

```text
POST /excel/ingest
GET  /excel/clauses
GET  /excel/standard-validity
```

Word 模板：

```text
POST   /templates/upload
GET    /templates
GET    /templates/{template_id}
DELETE /templates/{template_id}
```

知识问答 `/knowledge/*` 已删除。

## 6. 数据库

Harness 表：

- `agent_sessions`：聊天、摘要与结构化资源指针；
- `agent_tasks`：一次用户目标；
- `agent_episodes`：一次完整尝试；
- `agent_steps`：单步 action/observation；
- `agent_experiences`：candidate/active/retired Insight。

业务表：

- `check_runs`：文档检查事实；
- `word_edit_runs`：修改计划、changes、输出与复检；
- `word_documents`、`word_references`、`word_sections`、`check_issues`；
- `mandatory_clauses`、`standard_validity_records`；
- `word_templates`、`word_template_headings`、`word_template_key_sections`。

旧 `knowledge_documents`、`clause_extraction_runs` 表会在 `init_db()` 时删除。

## 7. Excel 初始化

```bash
python -m app.cli.inspect_excel "../强制性条文整理20260507.xlsx"
python -m app.cli.ingest_excel_pg "../强制性条文整理20260507.xlsx" --replace
```

## 8. 测试

```bash
ruff check app tests
python -m pytest -q -p no:cacheprovider
```

当前数据库初始化方式适合本地开发。生产环境应改用 Alembic，并在执行删除旧表的迁移前备份历史数据库。
