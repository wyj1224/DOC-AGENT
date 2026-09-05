# 灵枢·规鉴

面向通信工程设计说明的文档检查与安全自动修订 Agent。

后端已统一为 `Session -> Task -> Episode -> Step` 的 Agent Harness。每个 Episode 使用 ReAct 循环调用细粒度工具，结束后由确定性 Evaluator 查询数据库、文件和工具事实；可重试失败会生成 Reflection，最多创建第二个 Episode。经失败后成功验证的经验会成为同一用户、同一业务可复用的 active Insight。

项目不再包含知识文档问答 RAG、Embedding 或 Milvus。

## 功能

- Word 一致性检查：核对设计依据、正文引用与 PostgreSQL 标准库。
- Word 完整性检查：匹配模板，检查缺章、空正文、占位符和关键章节差异。
- Word 安全修订：模型只选择可修问题 ID，确定性代码生成修改并精确写回副本，再自动复检。
- Agent 运行记录：保存 Task、Episode、Step、Evaluator、Reflection 和 Experience。
- 会话记忆：保存聊天消息与摘要，同时单独维护 Word 与 Task 资源指针。
- 匿名访客隔离：同一浏览器通过签名 Cookie 恢复会话，不同访客的数据和 Experience 隔离。

## 结构

```text
backend/
├── app/agent/       # Harness、Environment、Evaluator、Memory、工具注册和工作流
├── app/db/          # SQLAlchemy 模型与初始化 DDL
├── app/services/    # Word 检查/修改、模板和会话服务
├── app/routers/     # FastAPI 接口
└── tests/           # Agent 与业务规则测试

frontend-vue2/       # 统一前端：Agent 工作台、强条库与 Word 模板管理
```

详细源码职责和执行流程见 [agent.md](./agent.md)，后端命令与接口见 [backend/README.md](./backend/README.md)。

## 本地启动

要求 Python 3.11、Node.js、Docker Desktop，以及 DeepSeek API Key。

```bash
cd backend
cp .env.example .env
python -m pip install -r requirements.txt
docker compose up -d postgres
python -m app.cli.init_db
python -m uvicorn app.main:app --reload
```

API：`http://127.0.0.1:8000`，Swagger：`http://127.0.0.1:8000/docs`。

公共前端：

```bash
cd frontend-vue2
npm install
npm run dev
```

打开 `http://127.0.0.1:5174`。左侧底部的“资料管理”可进入强条标准库和 Word 模板库；原独立管理员前端和知识问答界面已经移除。

## 数据初始化

```bash
cd backend
python -m app.cli.ingest_excel_pg "../强制性条文整理20260507.xlsx" --replace
```

Word 模板通过管理接口上传。旧知识问答资料不再入库。

## 主要 API

```text
POST /agent/check
POST /agent/check/stream
GET  /agent/sessions
GET  /agent/tasks
GET  /agent/tasks/{task_id}
GET  /agent/experiences

POST /word/upload
POST /word/check
POST /word/completeness-check
POST /word/fix-consistency
GET  /word/issues

POST /excel/ingest
GET  /excel/clauses
GET  /excel/standard-validity

POST   /templates/upload
GET    /templates
DELETE /templates/{template_id}
```

## 验证

```bash
cd backend
ruff check app tests
python -m pytest -q -p no:cacheprovider
```

## 当前边界

- `max_episodes=2`，不同 Environment 有独立 Step 上限。
- Experience 不做向量检索；每个 Task 开始时读取同 owner、同 task_type 最近 8 条 active Insight。
- Episode 1 失败产生 candidate；Episode 2 成功后 active，仍失败则 retired。
- `manual_review` 禁止自动 Retry；只有 `retryable_failure` 进入第二个 Episode。
- 前端已改用新的 Task、Episode、Step 和 Evaluation 字段展示运行轨迹。
- 当前使用启动时兼容 DDL；正式部署建议改用 Alembic。
