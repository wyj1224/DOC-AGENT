# DOC AGENT

面向通信工程设计说明的文档问答与校验智能体。项目当前已经打通匿名访客会话记忆、Word 一致性校验、Word 完整性校验、通用知识库 RAG、Agent 工具调用、公共工作台和独立资料管理页等主要链路。

当前已经打通“检查 -> Agent 读取结构化问题 -> 规划并修改 Word 副本 -> 重新解析与复检 -> Agent 判断继续或结束 -> 返回副本”的文档修改闭环。下一阶段的核心目标是建立正式的 RAG 评测集，并根据真实使用反馈继续补充回归样例。

## 已实现功能

### 1. 标准引用一致性校验

- 解析 `.docx` 中的标题、正文、表格和标准引用。
- 将“设计依据”和“编制依据”等依据章节与普通正文分开处理。
- 对比依据章节与 Excel 标准有效性库。
- 对比正文引用与依据章节。
- 支持标准替代、标准号不一致、标准名不一致、正文引用未在依据中声明、依据声明未使用等问题分类。
- 支持正文只写标准名、不写标准号的合法场景，降低误报。

### 2. 文档完整性校验

- 维护每年度的 `700M`、`室内`、`室外` 三类 Word 模板。
- 根据待检文件名自动识别年份和类型并匹配模板。
- 提醒疑似缺少章节、章节正文为空和正文存在占位符。
- 对“安全生产要求”“工程验收”“电磁防护与环境保护”执行确定性文本 Diff，列出正文新增、删除、修改和子章节编号变化。
- 三个关键章节文字相似度低于 95% 时报警；达到 95% 的实质差异仍保留为提示。
- 模板支持批量上传、持久化展示、展开标题和删除。

### 3. 通用知识库 RAG

- 使用 LlamaParse 将知识库文档解析为 Markdown。
- 使用 jieba 生成中文关键词稀疏向量。
- 使用千问 Embedding 生成稠密向量。
- 使用 Milvus Lite 执行固定权重混合检索：关键词 `0.6`，向量 `0.4`。
- 使用大模型生成带 `[1]`、`[2]` 引用编号的回答，并返回来源文件、页码、原文和得分。
- PostgreSQL 保存知识库文件及解析状态，Milvus 保存检索向量。

### 4. Agent 与会话记忆

- 大模型先规划工具，再由工具注册表执行确定性工具，最后生成回答。
- 支持 Word 解析、一致性检查、完整性检查、问题查询和知识库问答工具。
- 浏览器首次访问时自动获得签名 `visitor_id` Cookie；无需登录，不同浏览器的会话、文档和 Agent 运行记录仍相互隔离。
- 同一会话保存用户问题和最终回答，并将会话上下文提供给后续请求。
- 每累计 12 条未总结消息触发一次摘要，保留最近 6 条原始消息。
- 工具计划、工具结果和耗时保存在检查运行记录中，不混入日常对话记忆。
- 用户要求修改时，外层 Agent 工作流进入逐步循环，每次根据最新 Observation 选择 `inspect`、`prepare`、`apply`、`verify`、结束或转人工，而不是调用一个内含固定步骤的 Word 修改黑盒。
- 一次修改请求始终只对应一条 `WordEditRun`；`word_edit_runs.changes` 按 cycle 累积记录已规划、已应用和失败的修改，作为循环的核心持久化记忆。
- LLM 只决定下一动作和选择哪些可修问题，不生成标准号、标准名、`before/after` 或定位信息；替换值始终来自可审计的 `fix_data`，写回仍使用精确 `locator` 和 `span`。
- 每个 LLM 决策和工具结果都进入结构化 `agent_trace`，同时持久化到 `word_edit_runs.decision_trace`；`max_steps` 和 `max_cycles` 仅用于防止异常无限循环，不规定固定修改流程。

### 5. 前端工作台

- 公共工作台使用 Vue 2.7 + Vite，位于 `frontend-vue2/`，打开即可使用。
- 独立资料管理页位于 `frontend-admin-vue2/`，只包含知识库、Word 模板和 Excel 标准库。
- 旧 React 前端以及登录、注册和账户入口已移除。
- 左侧会话列表、新建对话和删除对话。
- 中间聊天式工作区，支持文字、Word 附件和流式回答。
- 右侧可展开结果面板，展示问题、引用来源和 Agent 执行信息。
- 自动修订完成后展示副本名称、修改数量、复检结果、LLM 决策次数、工具调用次数、执行循环和下载按钮。
- 公共工作台不展示资料维护入口；管理网址单独提供知识库、Word 模板和 Excel 标准库操作。

## 系统结构

```text
浏览器
  -> Vue 2 公共工作台（5174）/ Vue 2 资料管理页（5175）
  -> FastAPI 接口
     -> Agent 工作流与会话记忆
     -> Word 一致性/完整性服务
     -> 通用知识库 RAG
     -> PostgreSQL 结构化数据
     -> Milvus Lite 向量数据
     -> DeepSeek / 千问 / LlamaParse
```

项目详细代码地图、数据库表、业务规则和后续开发顺序见 [agent.md](./agent.md)。后端接口与命令速查见 [backend/README.md](./backend/README.md)。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 前端 | Vue 2.7、Vite、Lucide Icons |
| API | FastAPI、Uvicorn |
| ORM/数据库 | SQLAlchemy 2、PostgreSQL 16 |
| Word/Excel | python-docx、本地 Excel 解析 |
| RAG 解析 | LlamaParse |
| 中文分词 | jieba |
| Embedding | 千问 Embedding OpenAI Compatible API |
| 向量库 | Milvus Lite |
| Agent LLM | DeepSeek OpenAI Compatible API |
| 访客隔离 | HMAC 签名 HttpOnly Cookie、匿名访客记录 |

## 目录概览

```text
.
├── README.md                 # 项目入口、功能和启动说明
├── agent.md                  # 详细代码地图、功能状态和后续目标
├── backend/                  # FastAPI、数据库、Agent、校验和 RAG
├── frontend-vue2/            # Vue 2.7 公共文档工作台
├── frontend-admin-vue2/      # Vue 2.7 资料管理页
├── scripts/                  # 阶段报告等独立脚本
├── output/                   # 已生成的报告
├── 强制性条文整理20260507.xlsx # 当前标准有效性与强条数据源
└── *.docx                    # 示例或测试用设计说明
```

## 本地启动

### 1. 前置条件

- Python 3.11
- Node.js 与 npm
- Docker Desktop
- DeepSeek API Key
- 千问/阿里百炼 API Key
- LlamaParse API Key

### 2. 启动后端

```bash
cd backend
cp .env.example .env
```

在 `.env` 中配置 API Key 和 `VISITOR_COOKIE_SECRET`，然后执行：

```bash
python -m pip install -r requirements.txt
docker compose up -d postgres
python -m app.cli.init_db
python -m uvicorn app.main:app --reload
```

后端地址：`http://127.0.0.1:8000`

接口文档：`http://127.0.0.1:8000/docs`

### 3. 启动公共工作台

另开一个终端：

```bash
cd frontend-vue2
npm install
npm run dev
```

公共工作台地址：`http://127.0.0.1:5174`

前端默认请求 `http://127.0.0.1:8000`。如后端地址不同，可设置：

```bash
VITE_API_BASE=https://你的后端地址 npm run dev
```

### 4. 启动资料管理页

```bash
cd frontend-admin-vue2
npm install
npm run dev
```

资料管理页地址：`http://127.0.0.1:5175`。两个前端连接同一套后端和数据库；当前按网址入口隔离，不提供登录权限控制。

### 5. 首次使用

1. 维护人员打开 5175，上传 Excel 标准库、三个 Word 模板和知识库资料。
2. 普通使用者打开 5174，浏览器会自动建立匿名访客身份。
3. 新建对话，上传待检 Word 后输入“全面检查这个文档”。
4. 检查后继续输入“帮我修改”，系统会生成修订副本并自动复检。
5. 也可以切换到强条抽取或知识问答模式。
6. 刷新或重新打开同一浏览器时，会通过访客 Cookie 恢复历史会话。

## 可选命令

导入 Excel 到 PostgreSQL：

```bash
cd backend
python -m app.cli.ingest_excel_pg "../强制性条文整理20260507.xlsx" --replace
```

查看 Excel 结构：

```bash
cd backend
python -m app.cli.inspect_excel "../强制性条文整理20260507.xlsx"
```

运行当前 RAG 冒烟评测：

```bash
cd backend
python -m app.cli.eval_rag data/rag_eval/questions.example.jsonl --top-k 5
```

当前 `questions.example.jsonl` 仅用于验证评测程序可运行，不代表正式评测集。

## 当前边界

- 会话、上传文档、检查和 Agent 运行记录按匿名访客隔离；知识库、模板和 Excel 标准库是全局共享资料。
- 清除 Cookie、使用另一浏览器或更换设备后会获得新的访客身份，无法恢复原浏览器的会话。
- 资料管理页当前只通过独立网址隐藏入口，不提供应用层权限控制。
- 自动修订仅处理一致性检查的 `warning` 和 `high`，不修改 `info`，也不修改完整性提醒。
- 自动修订依赖新解析文档保存的精确位置；旧数据需重新上传并检查后才能写回。
- 当前已有 RAG 冒烟评测脚本，尚未建立覆盖真实业务问题的正式评测集。
- Vue 2 已停止官方维护；当前版本是满足既定技术要求的 Vue 2.7.16，依赖安全告警需要在部署前单独评估。

## 后续目标

1. 建立正式 RAG 测试集、评测指标和调参记录。
2. 增加修改前后差异确认和更完整的真实文档回归集。
3. 为一致性、完整性、RAG 和会话记忆补充自动化回归测试。
4. 完成公网部署、安全配置、日志与备份方案。

## 相关文档

- [代码地图与开发状态](./agent.md)
- [后端运行与接口说明](./backend/README.md)
- [后端入口、数据库和 Agent 代码详解](./后端入口数据库Agent代码详解.md)
- [现有代码流程逐行详解](./现有代码流程逐行详解.md)
- [RAG 冒烟测试说明](./backend/data/rag_eval/README.md)
