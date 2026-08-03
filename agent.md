# 灵枢·规鉴 代码地图与开发状态

本文档以当前仓库代码为准，主要用于后续学习、维护和继续开发。

- 最后核对日期：2026-07-21。
- 当前主链路：Word 一致性校核、完整性校核与三个关键章节 Diff、Word 修改 Agent Loop、PDF 强条抽取 Agent Loop、RAG 和会话记忆均已落地；系统已改为匿名访客直接使用，并拆分 Vue 2 公共工作台与资料管理页。

- 第一部分是完整代码地图，说明主要目录和源码文件分别负责什么。
- 第二部分以后记录模块边界、运行流程、数据库、业务规则、当前完成情况和后续目标。
- 本文不逐行解释代码。需要逐行阅读时，可配合根目录的 `后端入口数据库Agent代码详解.md` 和 `现有代码流程逐行详解.md`。

## 1. 功能模块代码树

### 1.1 根目录

```text
灵枢·规鉴/
├── .gitattributes
│   └── 自动识别文本文件并统一使用 LF 换行
├── .gitignore
│   └── Python 缓存、本地环境、上传文件、构建产物等忽略规则
├── README.md
│   └── 项目入口、功能概览、本地启动和当前边界
├── agent.md
│   └── 当前代码地图、功能状态、业务规则和后续开发目标
├── backend/
│   └── FastAPI 后端、Agent、数据库、校验服务和 RAG
├── frontend-vue2/
│   └── Vue 2.7 公共文档工作台，无需登录
├── frontend-admin-vue2/
│   └── Vue 2.7 资料管理页，只维护知识库、Word 模板和 Excel 标准库
├── scripts/
│   └── 与在线系统分开的报告生成脚本
├── output/
│   └── 已生成的阶段报告等交付文件
├── tmp/
│   └── PDF 渲染图片等临时验证文件，不是业务源码
├── 强制性条文整理20260507.xlsx
│   └── 当前标准有效性关系和强制性条文的主要 Excel 数据源
├── *.docx
│   └── 示例、原始设计说明或测试文档
├── 后端入口数据库Agent代码详解.md
│   └── 后端入口、数据库和 Agent 的辅助学习文档
└── 现有代码流程逐行详解.md
    └── 主要处理流程的辅助学习文档
```

### 1.2 后端顶层配置

```text
backend/
├── README.md
│   └── 后端安装、环境变量、数据库、接口和命令速查
├── requirements.txt
│   └── Python 依赖及建议的 Python 版本
├── docker-compose.yml
│   └── 本地 PostgreSQL 16 容器与持久化卷配置
├── .env.example
│   └── 可公开的环境变量模板
├── .env
│   └── 本机密钥与运行配置，不应提交或复制到文档
└── data/
    ├── milvus.db/
    │   └── Milvus Lite 本地数据库目录，运行后生成
    ├── edits/
    │   └── Word Agent Loop 按 edit_run_id/cycle 保存的中间修订副本
    ├── clause_extractions/
    │   └── 强条抽取 Agent 按 extraction_run_id 保存的 PDF 分页解析缓存
    ├── chunks_preview.jsonl
    │   └── Excel 强条切块预览结果
    ├── standard_validity_preview.jsonl
    │   └── 标准有效性数据预览结果
    ├── rag_eval/
    │   ├── README.md
    │   │   └── 冒烟评测数据格式和执行方式
    │   ├── questions.example.jsonl
    │   │   └── 来源命中与关键词命中的示例问题集
    │   └── smoke_knowledge.md
    │       └── 用于验证入库和召回链路的最小知识文本
    └── uploads/
        ├── knowledge/
        │   └── 上传的通用知识库原文件
        ├── excel/
        │   └── 上传的 Excel 标准库原文件
        ├── templates/
        │   └── 上传的 Word 模板原文件
        ├── clause_extraction/
        │   └── 上传后由强条抽取 Agent 单次处理的 PDF，不进入知识库
        └── word/
            └── 上传的待检 Word 原文件
```

`backend/data/uploads/`、`backend/data/milvus.db` 和 `__pycache__/` 都是运行数据或缓存，不属于核心学习源码。

### 1.3 后端应用入口与基础组件

```text
backend/app/
├── __init__.py
│   └── Python 包标记
├── main.py
│   └── 创建 FastAPI 应用、配置 CORS、注册全部路由、启动时初始化数据库
├── config.py
│   └── 读取路径、数据库、访客 Cookie、DeepSeek、千问文本/视觉、LlamaParse 和 Milvus 配置
├── visitor.py
│   └── 生成并校验签名 visitor Cookie，将匿名浏览器映射为内部 owner_user_id
├── llm.py
│   └── 创建 OpenAI Compatible 大模型客户端、统一调用 DeepSeek，并提供用户报告的统一排版规范
├── schemas.py
│   └── 跨模块共用的数据结构；`TextChunk.as_milvus_row()` 负责把切块和稠密向量转换为强条 Milvus 集合要求的入库字段
├── chunking.py
│   └── 通用文本和 Markdown 切块辅助逻辑
├── excel_loader.py
│   └── 读取 Excel sheet、识别列并生成强条及标准有效性结构
├── word_loader.py
│   └── 按 Word 原始顺序读取段落和表格，维护标题路径并保存可写回容器位置
├── embedding_qwen.py
│   └── 调用千问 Embedding 接口、控制批量大小并返回稠密向量
├── keyword_embedding.py
│   └── jieba 中文分词、关键词权重和 Milvus 稀疏向量生成
├── milvus_store.py
│   └── 强制性条文向量集合的创建、写入和检索
└── knowledge_store.py
    └── 通用知识库双向量集合、混合检索、加载和文档向量删除
```

### 1.4 API 路由层

```text
backend/app/routers/
├── __init__.py
│   └── 路由包标记
├── system.py
│   └── 健康检查接口 GET /health
├── agent.py
│   └── Agent 普通/流式请求、会话历史、运行记录和删除接口 /agent/*
├── word.py
│   └── Word 上传、检查、Agent Loop 修订、问题/章节查询和副本下载 /word/*
├── excel.py
│   └── Excel 上传入库、强条和标准有效性记录查询 /excel/*
├── templates.py
│   └── Word 模板批量上传、列表、详情和删除 /templates/*
└── knowledge.py
    └── 通用知识库上传、列表、删除和问答 /knowledge/*
```

路由层负责 HTTP 参数、上传文件、匿名访客依赖和响应格式；核心业务放在 `services/` 或 `agent/` 中。知识库、模板和 Excel 管理接口不绑定访客，作为共享资料维护接口使用。

### 1.5 Agent 编排层

```text
backend/app/agent/
├── __init__.py
│   └── Agent 包标记
├── registry.py
│   └── 普通 Planner 工具与 Word Loop 工具的独立 allowlist、说明和统一调度入口
├── tools.py
│   └── 将 RAG、Word 解析、两类检查和问题查询封装成普通 Agent 工具
├── word_edit_tools.py
│   └── 封装检查问题、准备修改、执行 Word 写入和复检四个细粒度工具
├── clause_extraction_tools.py
│   └── 封装 PDF 检查、候选条文抽取和结果验证三个细粒度工具
└── workflow.py
    └── 顶层模式识别、Word/强条 Agent Loop、最终回答、运行记录和会话记忆主流程
```

普通 Planner 可以调用以下 5 个工具：

| 工具 | 文件 | 职责 |
| --- | --- | --- |
| `knowledge_query_tool` | `agent/tools.py` | 混合检索知识库并生成带引用回答 |
| `parse_word_tool` | `agent/tools.py` | 解析 Word，保存文档、引用和章节 |
| `word_check_tool` | `agent/tools.py` | 执行依据与 Excel、正文与依据的一致性检查 |
| `completeness_check_tool` | `agent/tools.py` | 匹配模板并执行完整性检查 |
| `get_issues_tool` | `agent/tools.py` | 按文档、范围、类型和严重程度查询问题 |

外层 Word Agent Loop 逐步调用的细粒度工具位于 `agent/word_edit_tools.py`：

| 工具 | 职责 |
| --- | --- |
| `inspect_consistency_issues_tool` | 重新检查并返回可供 LLM 判断的结构化问题 |
| `prepare_word_edit_tool` | 将 LLM 选择的问题转换为固定、可审计的 changes |
| `apply_word_edit_tool` | 使用精确 locator 修改 Word 副本并重新解析 |
| `verify_word_edit_tool` | 对 apply 阶段已经重新解析的副本执行一致性复检并返回剩余问题 |

强条抽取 Agent Loop 逐步调用的工具位于 `agent/clause_extraction_tools.py`：

| 工具 | 职责 |
| --- | --- |
| `inspect_clause_pdf_tool` | 判断公告/黑体规则/无强条证据；公告支持展开到“条 + 第几款”，黑体型按原页笔画筛行并让视觉模型读取条号，同时准备可检索的分页正文 |
| `extract_clause_candidates_tool` | 根据已确认的条号或款级引用在分页正文中逐项定位内容，不依据 Markdown 粗体或强制措辞猜测强条 |
| `verify_clause_candidates_tool` | 按强制执行单元检查公告引用是否缺失、粗体证据是否可确认，并决定完成还是进入人工复核 |

### 1.6 业务服务层

```text
backend/app/services/
├── __init__.py
│   └── 服务包标记
├── excel_ingest.py
│   └── 将 Excel 强条和标准有效性记录写入 PostgreSQL
├── word_references.py
│   └── 从 Word 文本中抽取标准号、标准名、文件号、条号和上下文
├── section_scope.py
│   └── 判断章节属于设计依据/编制依据还是普通正文
├── word_sections.py
│   └── 提取真实 Word 标题，建立章节区间并收集两个标题之间的正文
├── word_check.py
│   └── 一致性规则、匹配优先级、问题分类、固定修复数据和结果写库
├── word_editor.py
│   └── 根据容器位置和字符区间修改 python-docx run，并保存 Word 副本
├── word_edit_workflow.py
│   └── 单条 WordEditRun、累计 changes、四个修订工具、状态校验和执行轨迹持久化
├── template_ingest.py
│   └── 从模板文件名推断年份/类型，提取标题，并保存三个关键章节的文本快照
├── key_section_diff.py
│   └── 提取三个关键章节及其子章节树，严格比较正文和子章节编号并计算文字相似度
├── completeness_check.py
│   └── 模板匹配、缺少标题、正文为空、占位符和关键章节差异检查
├── clause_extraction.py
│   └── 强条抽取任务、PDF 分页缓存、原生文字层/OCR 回查、条及款级引用展开、正文定位、结果验证、任务记忆和追问回答
├── pdf_vision.py
│   └── 用 PyMuPDF 渲染页面、按相对笔画筛选粗体行，并通过百炼视觉模型读取结构化条号证据
├── knowledge_base.py
│   └── LlamaParse 解析、切块、向量化、Milvus 入库、检索和引用回答
└── session_memory.py
    └── 创建/读取会话、追加消息、构建上下文和触发历史摘要
```

### 1.7 数据库层

```text
backend/app/db/
├── __init__.py
│   └── 数据库包标记
├── database.py
│   └── SQLAlchemy Engine、SessionLocal、建表和兼容性字段/索引补齐
└── models.py
    └── 全部 PostgreSQL ORM 模型和索引定义
```

`models.py` 当前包含 15 个业务模型：

| 模型/表 | 主要用途 |
| --- | --- |
| `User / users` | 内部匿名访客映射；沿用原表名以避免重建全部 owner 外键，登录密码字段不再使用 |
| `MandatoryClause / mandatory_clauses` | 强制性条文结构化记录 |
| `StandardValidityRecord / standard_validity_records` | 新旧标准替代和有效日期 |
| `KnowledgeDocument / knowledge_documents` | RAG 文件、解析状态、页数和切块数 |
| `WordDocument / word_documents` | 上传的待检 Word 文档及本地路径；修订副本用唯一的 `edit_run_id + edit_cycle` 关联回 Agent Loop |
| `WordTemplate / word_templates` | 模板文件、年份、类型和标题数 |
| `WordTemplateHeading / word_template_headings` | 模板标题名称、层级和顺序 |
| `WordTemplateKeySection / word_template_key_sections` | 模板中安全生产要求、工程验收、电磁防护与环境保护三章的正文、子章节编号和结构化文本块 |
| `WordReference / word_references` | Word 中抽出的标准引用及精确写回位置 `locator` |
| `WordSection / word_sections` | Word 标题和标题之间的正文区间 |
| `CheckIssue / check_issues` | 一致性和完整性问题；一致性问题可带固定 `fix_data` |
| `CheckRun / check_runs` | 单轮 Agent 运行；通过 `session_id` 归属会话，`run_type` 区分 word_check、word_edit、knowledge、clause_extract 等类型，并保存计划、工具结果、回答、耗时和状态 |
| `WordEditRun / word_edit_runs` | 每次 Word 修改请求的唯一任务；`changes` 累积保存所有 cycle 的修改记忆，同时保存 LLM/工具轨迹、最新输出文档、复检和状态 |
| `AgentSession / agent_sessions` | 用户会话、消息 JSONB、摘要和最近文档/运行关联 |
| `ClauseExtractionRun / clause_extraction_runs` | 单次 PDF 强条抽取任务；保存文件指纹、状态、识别方法、`result_json`、Agent 决策轨迹和复核信息 |

### 1.8 命令行工具

```text
backend/app/cli/
├── __init__.py
│   └── CLI 包标记
├── init_db.py
│   └── 初始化或补齐 PostgreSQL 表结构
├── inspect_excel.py
│   └── 查看 Excel sheet、列名和样例数据
├── ingest_excel.py
│   └── 预览 Excel 强条切块并导出 JSONL
├── ingest_excel_pg.py
│   └── 将 Excel 标准库导入 PostgreSQL
├── search.py
│   └── 命令行测试强条 Milvus 检索
└── eval_rag.py
    └── 读取 JSONL 问题集并统计来源与关键词检索命中率
```

### 1.9 后端自动化测试

```text
backend/tests/
├── test_clause_extraction_agent.py
│   └── 验证强条 Agent 单步循环、动作约束、视觉证据合并、原生文字层回查、OCR 断行纠偏、公告款级展开和正文定位
├── test_pdf_vision.py
│   └── 验证视觉模型 JSON 规范化、缺页降级和结构化响应解析
├── test_key_section_diff.py
│   └── 验证三个关键章节子树提取、正文差异和子章节编号变化
├── test_word_edit_agent.py
│   └── 验证单条 WordEditRun、多 cycle 规划、状态动作约束、失败关闭和最终文档推断
├── test_word_editing.py
│   └── 验证精确字符区间写回、原件不变以及 Word run 样式保留
├── test_run_tracking.py
│   └── 验证运行类型识别，以及只有 Word 检查会更新最近 Word 校核指针
└── test_visitor.py
    └── 验证匿名访客 Cookie 签名、恢复和篡改拒绝
```

当前自动化回归共 32 项，覆盖强条抽取、关键章节 Diff、Word 修改 Agent 状态约束、运行类型追踪、精确写回和访客 Cookie。最近一次完整运行结果为 32/32 通过。

### 1.10 Vue 2.7 公共工作台代码树

```text
frontend-vue2/
├── package.json
│   └── Vue 2.7、Vite、Lucide Vue 依赖及 dev/build/preview 命令
├── package-lock.json
│   └── npm 锁定依赖版本
├── vite.config.js
│   └── Vue 2 插件和本地 5174 端口
├── index.html
│   └── 浏览器 HTML 入口
├── .env.example
│   └── 可选的 VITE_API_BASE 配置示例
├── README.md
│   └── Vue 2 公共工作台启动说明和匿名访客边界
└── src/
    ├── main.js
    │   └── Vue 2 应用挂载入口
    ├── App.vue
    │   └── 无登录根组件，直接进入公共工作区
    ├── styles.css
    │   └── 完整浅色工作台、三栏布局、输入区、结果面板和响应式样式
    ├── lib/
    │   ├── api.js
    │   │   └── API Base、携带 Cookie 的 REST/SSE、AbortController 和下载逻辑
    │   └── labels.js
    │       └── 问题类型、范围和严重程度的中文显示名称
    └── components/
        ├── Workspace.vue
        │   └── 匿名会话、附件、三模式、流式请求和结果状态协调
        ├── AppSidebar.vue
        │   └── 新建对话、当前访客历史会话和删除入口
        ├── ChatWorkspace.vue
        │   └── 三模式输入区、紧凑附件、IME 安全回车和发送/停止同键交互
        ├── ResultPanel.vue
        │   └── 校核、强条、RAG、Word 修改结果和 Agent Trace
        ├── ReportMarkdown.vue
        │   └── 先转义 HTML、再渲染有限 Markdown 的安全报告组件
        └── EmptyState.vue
            └── 空结果占位组件
```

### 1.11 Vue 2.7 资料管理页代码树

```text
frontend-admin-vue2/
├── package.json / package-lock.json
│   └── Vue 2.7、Vite、Lucide Vue 依赖和锁定版本
├── vite.config.js
│   └── 独立 5175 开发端口
├── index.html
│   └── 资料管理页面入口
└── src/
    ├── main.js
    │   └── Vue 挂载入口
    ├── App.vue
    │   └── 知识库、Word 模板、Excel 标准库三个维护模块及全部交互状态
    ├── lib/api.js
    │   └── 共用 8000 后端的请求和错误处理
    └── styles.css
        └── 复用公共视觉规范并补充独立管理页布局
```

公共工作台不包含管理入口。两套 Vue 前端共用 8000 后端、PostgreSQL、Milvus 和文件存储；`backend/app/main.py` 的本地 CORS 允许 5174 和 5175。当前资料管理页采用网址入口隔离，不做账号权限控制。

### 1.12 独立脚本与输出

```text
scripts/
└── build_phase1_report.py
    └── 生成第一阶段一致性校核项目报告

output/pdf/
└── 通信工程设计说明强制性条文引用一致性校核第一阶段报告.pdf
    └── 已生成的第一阶段报告
```

## 2. 模块边界与依赖关系

| 模块 | 输入 | 核心处理 | 输出/存储 |
| --- | --- | --- | --- |
| 匿名访客 | 浏览器 Cookie | HMAC 签名、自动创建内部访客映射 | `users`、HttpOnly Cookie |
| 会话记忆 | 用户消息、会话 ID | 上下文拼接、阶段摘要 | `agent_sessions` |
| Agent 编排 | 用户意图、附件、上下文 | 识别 standard/word_edit/clause_extract；普通工具计划或逐步 Agent Loop | `check_runs`、任务表、流式回答 |
| Word 修改 Agent | 修改意图、当前文档、数据库状态 | 推导允许动作、LLM 单步决策、确定性写回和复检 | `word_edit_runs.changes/decision_trace`、修订副本、复检记录 |
| 强条抽取 Agent | 单次 PDF、会话上下文、任务状态 | 自动判断证据类型、逐步检查/抽取/验证、按“条/款”强制执行单元计数、LLM 终止决策 | `clause_extraction_runs.result_json/decision_trace`、分页缓存 |
| Excel 标准库 | `.xlsx` | sheet/列识别、结构化导入 | `mandatory_clauses`、`standard_validity_records` |
| Word 解析 | `.docx` | 标题、段落、表格、引用和章节区间 | `word_documents`、`word_references`、`word_sections` |
| 一致性校验 | Word 引用、Excel 标准库 | 规则匹配、优先级、去重 | `check_issues` |
| 完整性校验 | 待检 Word、模板标题与三个关键章节快照 | 模板匹配、标题/正文/占位符检查、关键章节正文与子章节编号 Diff、95% 阈值判断 | `word_template_key_sections`、`check_issues` |
| RAG 入库 | PDF/Word 等知识文件 | LlamaParse、切块、分词、Embedding | PostgreSQL、Milvus |
| RAG 问答 | 自然语言问题 | 混合检索、引用编号、LLM 总结 | 回答与来源切块 |
| 公共前端 | 用户操作 | Vue 2.7 工作台切换三种模式，通过访客 Cookie 复用 API/SSE 和会话历史 | 聊天界面、结果面板 |
| 管理前端 | 资料文件 | 独立 Vue 2.7 页面维护知识库、Word 模板和 Excel 标准库 | 全局共享资料 |

## 3. 主要运行流程

### 3.1 Agent 会话流程

```text
浏览器直接发送消息/附件
  -> 后端校验或创建 visitor Cookie，并映射内部 owner_user_id
  -> 根据 session_id 读取或新建该访客的会话
  -> 将摘要和最近消息拼成对话上下文
  -> 前端模式与 Planner 共同确定 standard、word_edit 或 clause_extract
  -> standard：Planner 生成普通工具 steps，registry 顺序调用确定性工具
  -> word_edit：steps 强制为空，进入第 3.5 节的逐步 Agent Loop
  -> clause_extract：上传 PDF 时进入第 3.6 节的强条抽取 Agent Loop；追问时复用当前任务结果
  -> 保存 CheckRun 的计划、工具结果和状态
  -> Final Answer 结合上下文和工具结果生成中文回答
  -> 通过 SSE 向前端输出
  -> 将用户消息和最终回答写入 AgentSession.messages
  -> 达到阈值时更新 AgentSession.summary
```

当前会话记忆规则：

| 项目 | 当前规则 |
| --- | --- |
| 访客隔离 | 签名 Cookie -> 内部 `users.id` -> `agent_sessions.owner_user_id` |
| 会话隔离 | 每个会话单独一个 `session_id` |
| 消息存储 | `messages` JSONB，只保存用户消息和最终回答 |
| 摘要阈值 | 每累计 12 条未总结消息触发摘要 |
| 原文保留 | 保留最近 6 条消息参与后续上下文 |
| 当前文档 | `active_document_id` |
| 最近运行 | `last_run_id` |
| 最近 Word 校核 | `last_word_check_run_id`；只在 `run_type=word_check` 时更新 |
| 最近修改任务 | `active_edit_run_id` |
| 最近强条任务 | `active_clause_extraction_run_id` |
| 工具 Trace | 保存在带 `session_id/run_type` 的 `check_runs`，不作为另一套日常对话记忆 |

### 3.2 一致性校验流程

```text
上传 Word
  -> 解析标题、章节正文、表格和标准引用
  -> 标记依据章节与普通正文
  -> 依据章节 vs Excel 标准有效性库
  -> 正文 vs 依据章节
  -> 按优先级分类并去重
  -> 写入 check_issues
  -> Agent 生成汇总回答，右侧面板展示详情
```

### 3.3 完整性校验流程

```text
模板入库
  -> 从文件名识别年份和 700M/室内/室外
  -> 提取真实 Word 标题
  -> 保存模板、标题列表和三个关键章节的完整子章节树

上传待检 Word
  -> 从文件名识别年份和类型
  -> 匹配最近上传的同年同类型模板
  -> 比较标题名称
  -> 检查两个标题之间是否有有效正文
  -> 检查正文占位符
  -> 逐项比较安全生产要求、工程验收、电磁防护与环境保护
  -> 子章节按标题名称对齐，严格比较编号、正文新增/删除/修改
  -> 计算确定性文字相似度；低于 95% 报警，达到 95% 的差异仍作为提示列出
  -> 生成完整性问题
```

### 3.4 通用知识库 RAG 流程

```text
上传知识文件
  -> LlamaParse 转 Markdown
  -> 按页和约 700 字切块
  -> jieba 分词生成稀疏向量
  -> 千问生成稠密向量
  -> 写入 Milvus knowledge_chunks
  -> PostgreSQL 保存文件和解析状态

用户提问
  -> 问题分词 + 问题 Embedding
  -> 关键词 0.6 + 向量 0.4 混合检索
  -> 返回 Top K 原文
  -> DeepSeek 仅依据检索材料生成带编号回答
  -> 前端展示回答和引用来源
```

项目中有两个不同的 Milvus 集合：`mandatory_clause_chunks` 是早期 Excel 强条的单稠密向量集合，仅由 `cli/ingest_excel.py`、`milvus_store.py` 和 `cli/search.py` 使用；`TextChunk.as_milvus_row()` 正是该集合的入库字段适配器。当前前端知识问答使用的是 `knowledge_chunks` 双向量集合，由 `KnowledgeMilvusStore` 单独组装入库行，不调用 `as_milvus_row()`。因此这个方法当前不是死代码，但也不属于通用 RAG 主链路。

### 3.5 一致性自动修订流程

当前实现不是由 Planner 预先生成 `检查 -> 规划 -> 修改 -> 复检` 的固定步骤。Planner 只识别 `word_edit` 模式并将普通 `steps` 置空；之后由外层 Agent Loop 每次读取最新状态，让 LLM 只选择一个当前允许的下一动作。

```text
用户在检查后输入“帮我修改”
  -> Planner 返回 mode=word_edit、steps=[]
  -> start_word_edit_run 创建且只创建一条 WordEditRun
  -> 循环开始
       1. 从 PostgreSQL 重新读取 WordEditRun 状态和累计 changes
       2. 服务端根据状态、上一条 Observation 和预算推导 allowed_actions
       3. LLM 只返回一个动作：call_tool / finish / manual_review
       4. 服务端校验动作和参数，并把本次 LLM 决策写入 decision_trace
       5. call_tool 时只执行一个细粒度工具，并把工具 Observation 写入 decision_trace
       6. 回到第 1 步，基于新状态再次决策
  -> finish 或 manual_review 时由服务端重新校验数据库并关闭任务
  -> 结果通过 CheckRun、SSE 和历史接口返回，前端展示 Trace、摘要和副本下载
```

#### 3.5.1 状态与允许动作

`allowed_actions` 由服务端生成，LLM 不能绕过状态机自由调用工具：

| 数据库状态 | 满足条件时允许的下一动作 |
| --- | --- |
| `planning` | `inspect_consistency_issues_tool` 或 `manual_review` |
| `awaiting_plan` | 无问题时 `finish`；存在可自动修改问题且未超轮次预算时 `prepare_word_edit_tool`；也可 `manual_review` |
| `ready` | 存在 `pending changes` 时只能执行 `apply_word_edit_tool` |
| `applied` | 已有输出文档时只能执行 `verify_word_edit_tool` |
| `awaiting_decision` | 复检无剩余问题且无失败项时 `finish`；仍有新的可修改问题且未超预算时再次 `prepare_word_edit_tool`；也可 `manual_review` |
| `failed` | 动作规则只保留 `manual_review`；但当前异常路径会写入 `failed` 后直接向上抛出，不会自动恢复循环 |
| `completed` / `manual_review` | 终态，不再进入普通循环 |

`inspecting`、`applying`、`verifying` 是工具事务内的执行中状态；正常提交后会分别落到 `awaiting_plan`、`applied`、`awaiting_decision` 等稳定状态。

#### 3.5.2 四个单步工具

| 工具 | 单步职责 | 关键约束 |
| --- | --- | --- |
| `inspect_consistency_issues_tool` | 检查当前工作文档并创建初始 `CheckRun`，返回结构化问题和 `auto_fixable` 标记 | 当前文档是 `output_document_id`，没有输出时才使用原始 `source_document_id` |
| `prepare_word_edit_tool` | 校验 LLM 选择的 `issue_id`，从 `CheckIssue.fix_data` 与 `WordReference.locator/span` 生成可信修改指令，并追加一个新 cycle | 只接受 `basis_excel/body_basis` 范围内的 `warning/high` 问题；LLM 不能生成修改文本或位置 |
| `apply_word_edit_tool` | 只执行最新 cycle 的 `pending changes`，写入新的 Word 副本，并调用 `parse_word_tool` 解析该副本 | 每轮都以上一版输出为输入；原始 Word 永不覆盖 |
| `verify_word_edit_tool` | 对 `apply` 阶段已经解析入库的最新副本执行一致性复检，创建复检 `CheckRun` 并标记本轮验证结果 | 本工具不再次解析 Word；只有复检后 Agent 才能完成或规划下一轮 |

这些工具包含重复调用保护：相同检查结果、相同待执行批次、已经生成的输出和已经完成的复检会返回现有结果；`semantic_fingerprint` 会阻止跨 cycle 重复尝试同一语义修改。

#### 3.5.3 数据库记忆与 `changes`

一次用户修改请求只创建一条 `WordEditRun`，其角色是整个 Loop 的持久化工作记忆：

| 字段 | 含义 |
| --- | --- |
| `source_document_id` | 不变的原始文档 ID |
| `output_document_id` | 当前最新修订副本 ID；尚未生成副本时为空 |
| `source_check_run_id` | 本次 Loop 使用的初始检查记录 |
| `verification_run_id` | 最新一次复检记录 |
| `status` / `error_message` | 状态机状态和异常信息 |
| `changes` | 所有 cycle 累计的结构化修改指令和执行/验证结果 |
| `decision_trace` | 每次 LLM 决策与每次工具 Observation 的可审计轨迹 |
| `session_id` | 所属 Agent 会话 |

`changes` 是一份扁平、累计的 JSONB 列表，不会为每个 cycle 新建 `WordEditRun`。每条 change 的关键字段包括：

- 身份与去重：`schema_version`、`change_id`、`issue_fingerprint`、`semantic_fingerprint`、`cycle`。
- 文档链路：`input_document_id`、`output_document_id`。
- 问题来源：`issue_id`、`word_reference_id`、`issue_type`、`severity`。
- 确定性写回：`target`、`before`、`after`、`locator`、`span`。
- 执行状态：`status=pending/applied/failed`、`error`、`planned_at`、`applied_at`。
- 复检状态：`verification_run_id`、`verification_status=pending/checked`、`verified_at`。

只有 `prepare`、`apply` 和 `verify` 会更新 `changes`；LLM 决策和工具返回写入 `decision_trace`。上一条 `latest_observation` 是当前 Python 进程内的循环变量，未单独存入数据库，因此数据库状态、`changes` 和 Trace 可以审计，但服务进程中断后目前不会自动从中断点恢复 Loop。

启动任务时只更新会话的 `active_edit_run_id`；最终 `finish/manual_review` 时才把最终文档写入 `AgentSession.active_document_id`，并在存在复检时更新 `last_word_check_run_id`。

#### 3.5.4 决策安全、终止条件与预算

- LLM 只能从服务端给出的 `allowed_actions` 中选择，并且每次最多调用一个工具。
- 只有 `prepare_word_edit_tool` 接受 LLM 参数，参数也只允许是当前 Observation 中 `auto_fixable=true` 的 `selected_issue_ids`；`document_id`、用户 ID、`before/after` 和定位信息全部由服务端注入或读取。
- LLM 输出格式或动作无效时会纠正后重试一次；连续两次无效则任务记为 `failed` 并结束请求。
- `finish` 必须满足：没有 `pending changes`、数据库中已无 `warning/high` 一致性问题、所有 change 均无失败项；如果生成过修订副本，还必须存在复检记录。
- 无法安全定位、没有新的可修改问题、达到安全预算或 Agent 判断需要确认时，以 `manual_review` 结束；异常则写入 `failed`。
- `max_edit_cycles` 默认 3，限制在 1～5；`max_steps` 默认是 `max(8, max_edit_cycles * 4 + 4)`，限制在 4～32。它们只是安全上限，不是预置固定轮数。当前没有独立的“无进展计数器”，重复修改主要由 `semantic_fingerprint` 拦截。

#### 3.5.5 API 与前端结果契约

最终结果以 `word_edit_result` 包装后放入顶层 `CheckRun.tool_results`；这是兼容普通 Agent 结果结构的终态信封，不是 LLM 可以调用的工具。数据库终态是 `completed/manual_review/failed`，对外兼容状态为 `completed/partial`，并通过 `final_action=finish/manual_review` 表达 Agent 的结束选择。

主要返回字段包括 `source_document_id`、最终 `document_id`、可选的 `output_document_id/output_file_name/download_url`、`edit_run_id`、`attempt_count`、`planned_count`、`applied_count`、`failed_count`、`remaining_issue_count`、`llm_decision_count`、`tool_call_count`、`agent_trace`、`changes`、`passes` 和 `message`。没有生成副本时仍会返回 Trace 与说明，只是不显示下载入口。

流式接口先通过 SSE 的 `result` 事件返回 `tool_results`，再输出回答文本；`GET /agent/runs/{id}` 可以从历史记录恢复同一结果。前端识别新的 `word_edit_result`，同时保留旧 `fix_consistency_issues_tool` 名称的读取兼容。直接接口 `POST /word/fix-consistency` 的表单参数仍名为 `max_attempts`，内部会映射为 `max_edit_cycles`。

完整性问题和 `info` 一律不进入 `changes`。LLM 不允许修改 `before/after`、`fix_data`、`locator` 或 `span`，只能从当前文档中拥有精确位置的候选问题中选择 ID。实际 Word 写入仍是可审计的确定性工具，原件始终不覆盖。

### 3.6 PDF 强制性条文抽取 Agent Loop

该功能位于同一个前端对话框的“强条抽取”模式中。用户只上传 PDF，不需要选择 PDF 属于“黑体标识”“公告列出”还是“无强条”；系统必须读取 PDF 后自动判断。上传文件是一次性任务输入，不进入 Milvus 知识库，也不改写 Excel 维护的 `mandatory_clauses`。

#### 3.6.0 当前强条抽取代码树

```text
frontend-vue2/src/
├── components/Workspace.vue
│   └── “强条抽取”模式、PDF 附件、SSE 请求、访客会话恢复和结果状态协调
└── components/ResultPanel.vue
    └── 强条数量、识别方法、warnings、条文列表和 Agent Loop Trace 展示

backend/app/
├── config.py
│   └── DASHSCOPE_API_KEY、视觉模型地址/名称和 LlamaParse 配置
├── routers/agent.py
│   └── /agent/check 与 /agent/check/stream；接收 mode=clause_extract 和 PDF
├── agent/
│   ├── workflow.py
│   │   └── run_clause_extraction_loop、动作白名单、LLM 单步决策、终止与追问复用
│   ├── clause_extraction_tools.py
│   │   └── inspect / extract / verify 三个细粒度工具的参数边界
│   └── registry.py
│       └── 强条工具注册、说明和统一 run_tool 调度
├── services/
│   ├── clause_extraction.py
│   │   └── ClauseExtractionRun 状态、缓存、三类证据合并、原生文字层/OCR 正文恢复、款级引用展开、正文定位、验证和结果序列化
│   ├── pdf_vision.py
│   │   └── PDF 渲染、前置页视觉分类、公告条/款结构化读取、相对笔画筛行和候选行条号 OCR
│   ├── knowledge_base.py
│   │   └── LlamaParse 普通/高精度分页正文 OCR；强条任务只复用解析函数，不进入知识库
│   └── session_memory.py
│       └── AgentSession 消息、摘要和当前任务上下文
└── db/
    ├── models.py
    │   └── ClauseExtractionRun 与 AgentSession.active_clause_extraction_run_id
    └── database.py
        └── 建表及开发期兼容字段补齐

backend/tests/
├── test_clause_extraction_agent.py
│   └── Loop 动作约束、公告优先级、原生文字层、OCR 断行、款级展开、正文定位、跨页与页脚过滤
└── test_pdf_vision.py
    └── 视觉 JSON、公告款级引用规范化、粗体像素行筛选和缺页降级
```

```text
用户在“强条抽取”模式上传 PDF
  -> 创建或按 file_hash + 版本复用 ClauseExtractionRun
  -> Agent Loop 每步从数据库重读任务状态
       1. planning：LLM 选择 inspect_clause_pdf_tool
       2. inspected：LLM 选择 extract_clause_candidates_tool
       3. extracted：LLM 选择 verify_clause_candidates_tool
       4. verified：依据 requires_review 选择 finish 或 manual_review
  -> 每次 LLM 决策和工具 Observation 写入 decision_trace
  -> 完整结构化结果写入 result_json
  -> 通过原有 /agent/check/stream、CheckRun 和 AgentSession 返回
  -> 同一会话继续提问时，直接读取当前 ClauseExtractionRun，不重新解析 PDF
```

#### 3.6.1 自动识别策略

| 识别结果 | 自动处理 |
| --- | --- |
| 公告直接列出强条条号 | 从公告页提取条号；出现“某条第 3、4 款”时展开成两个独立强制执行单元，再到全文逐项定位正文；缺失引用进入人工复核 |
| 正文以黑体/粗体标识强条 | 原页渲染后按黑色笔画密度和内部笔画像素筛出相对粗体行，再由视觉模型只读取候选行开头条号；随后到 OCR 正文中定位完整条文 |
| PDF 明确写“无强制性条文” | 记录为 `confirmed_none`，保留明确依据 |
| 未发现任何强条证据 | 记录为 `none_detected`，回答只能说“未识别到”，不能断言一定没有强条 |
| 解析质量低、公告条号缺失或黑体证据丢失 | 以 `manual_review` 结束并显示 warning，不让模型补写条文 |

这是一个有数据库状态、Observation、LLM 单步决策、工具调用、验证和终止判断的真实 Agent Loop，但刻意保持精简。PDF 文本解析和条文定位是确定性工具，LLM 不负责凭空抽取正文；它只依据 `ClauseExtractionRun` 状态选择当前允许动作，并在完成后基于 `result_json` 汇总或回答追问。

强条数量按“强制执行单元”计算，不只按主条号去重。整条强制时引用为 `1.0.3`；仅指定某款时内部引用为 `5.1.9#7`，用户界面显示为 `5.1.9 第7款`。例如公告中的“5.1.9 条第 7、8、9 款”会生成 3 条候选，每条分别带 `clause_no`、`item_no` 和 `reference`。因此一个公告即使只有 9 个主条号，也可能对应 12 个实际强条单元；验证、缺失列表、计数和最终回答都按这 12 个单元处理，不能再把同一主条号下的多款合并成一项。

检查工具先用 PyMuPDF 将前 12 个物理页面分成有重叠的上、中、下区域，并要求视觉模型返回固定 JSON：公告主条号、按款展开的 `announcement_clause_refs`、黑体标识规则、明确无强条声明和短证据。若前置公告已经给出完整引用，或明确声明没有强条，工具立即停止扩扫；公告优先级高于同页出现的黑体说明，因此 534 页公告型样例只需检查前 12 页。没有权威前置结论时才扫描剩余页面。

对于声明“黑体为强条”的 PDF，不把通用视觉模型的一次字体分类直接作为终值。系统以固定倍率渲染原页，屏蔽灰色水印，按页面普通正文的中位笔画特征动态计算阈值，筛出黑色笔画密度和内部笔画像素同时显著偏高的文本行；标题、表名等即使进入候选，视觉模型也只允许读取以完整规范条号开头的候选行。这样视觉模型负责文档类型判断和候选行 OCR，实际粗体判定来自原页像素，避免根据“必须、严禁、应、不得”措辞猜测，也避免一次模型调用的随机漏报/误报。

正文恢复按成本从低到高降级：先使用已通过质量校验的历史分页缓存；否则调用 LlamaParse 普通解析；普通解析质量低时，先用 PyMuPDF 回查 PDF 自带的原生文字/OCR 层；原生文字仍不足才对全部物理页执行 LlamaParse 高精度 OCR。OCR 只恢复文字，禁止自行添加粗体语义；随后以已确认的条号或款级引用为准定位完整正文。正文定位从“总则”后的规范正文开始，在“条文说明”前结束，并支持被换行拆开的条号（如 `5.\n1.\n9`）、数字 OCR 纠偏、款序号拆分、跨页正文合并以及水印和普通/圆点页码过滤。视觉调用失败、确认引用无法在正文定位、或 PDF 声明黑体规则但全文未确认到黑体条文时，任务带 warning 进入人工复核。

同一用户再次处理相同 `file_hash` 的 PDF 时，新的抽取算法版本可以复用历史 `parsed_pages_path`，避免仅因提示词或视觉算法升级而重新消耗数百页 OCR。复用前必须同时校验物理页数、非空页比例和总文本量；仅有 534 个空分页槽位不算有效缓存。命中有效缓存时记录 `body_cache` 和来源任务 ID，并视为正文已经完成验证，不再额外调用候选页高精度 OCR。若新 OCR 返回空内容或有效文本量不足，必须标记失败并进入复核，不能再把补齐后的空页面误判为成功。

#### 3.6.2 任务记忆与数据边界

`ClauseExtractionRun` 是强条抽取 Loop 的任务记忆，主要字段如下：

| 字段 | 含义 |
| --- | --- |
| `file_name/file_path/file_hash` | PDF 身份、存储位置和相同文件结果复用依据 |
| `parsed_pages_path` | 当前最终采用的分页正文 JSON 缓存，内容可来自历史缓存、LlamaParse 或 PDF 原生文字层 |
| `status/mandatory_status/error_message` | Loop 状态、强条判断和异常信息 |
| `detection_methods` | `vision_announcement`、`vision_bold_rule`、`vision_bold_body`、`vision_explicit_none`、`vision_no_evidence`、`body_native_text`、`body_high_accuracy`、`body_cache`，以及文本降级识别方法 |
| `page_count/clause_count` | 解析页数和最终候选数 |
| `result_json` | 标准信息、检查信号、条号/款号、`reference`、正文、页码、置信度、缺失引用和 warnings |
| `decision_trace` | LLM 决策与工具 Observation 的完整审计轨迹 |
| `parser_version/prompt_version` | 缓存复用和后续算法升级的版本边界；当前分别为 `12` 和 `2` |

`AgentSession.active_clause_extraction_run_id` 只保存当前会话指针，日常 `messages` 仍只保存用户消息和最终回答。大体积的 `result_json` 不复制进消息历史，因此用户可以在同一会话中按条号或章节继续提问，同时避免每次重新解析整份 PDF。

### 3.7 统一用户回答排版

所有面向用户的 LLM 回答共用 `app.llm.USER_REPORT_FORMAT_RULES`，覆盖普通文档校核、完整性汇总、知识库问答以及 PDF 强条抽取和追问。统一流程如下：

```text
结构化工具结果
  -> 叠加当前业务回答规则
  -> 叠加统一用户排版规则
  -> temperature=0 调用文本模型
  -> 前端 ReportMarkdown 渲染
```

统一规则只允许简短自然段、二级/三级标题、项目符号、编号列表、粗体和行内引用；禁止 Markdown 表格、竖线分隔内容、表格分隔行和代码块。同类问题先汇总数量，再列必要明细，不直接复制内部 JSON、英文状态字段或大段原文。

`ReportMarkdown` 是轻量渲染组件，只负责上述受控格式，不实现完整 GFM 表格。Word 修改终态消息由后端确定性代码生成，本身不经过自由排版。Planner、Word 修改 Agent 和强条抽取 Agent 的内部 JSON 决策不套用用户排版规则，避免影响工具调用。历史 `CheckRun.answer` 保留生成时的原文；新规则只作用于后续新回答。

## 4. 当前业务规则

### 4.1 依据章节与 Excel 标准库

当前内部检查范围为 `basis_excel`，优先级如下：

1. 优先识别 Word 中是否明确出现标准号或文件号。
2. 命中新标准号/新文件号时，不报标准替代。
3. 命中旧标准号/旧文件号时，报 `standard_replaced`。
4. 没有编号、只写标准名时，只有“明确命中旧名称且不命中新名称”才报替代。
5. 旧标准与新标准同名时，仅凭名称不能判断版本，不报替代。
6. 未命中替代关系后，再判断 `standard_not_found`。
7. 标准号存在但名称不同，报 `standard_name_mismatch`。
8. 标准名存在但标准号不同，报 `standard_no_mismatch`。

### 4.2 正文与依据章节

当前内部检查范围为 `body_basis`，优先级如下：

1. 正文明确写旧编号，依据明确写对应新编号时，优先报 `body_reference_replaced_by_basis`。
2. 正文只写标准名而未写编号时，允许按名称与依据匹配。
3. 正文和依据名称一致、正文缺少编号时，不报编号不一致。
4. 正文与依据命中同一标准关系但名称不同，报 `body_standard_name_mismatch`。
5. 正文与依据名称一致但明确编号不同，报 `body_standard_no_mismatch`。
6. 正文引用无法与依据中的名称或编号匹配，报 `body_reference_not_in_basis`。
7. 依据声明但正文未使用，报 `basis_declared_but_unused`，作为提示信息。
8. “设计依据”和“编制依据”等章节都归入依据范围，不参与普通正文引用缺失判断。

### 4.3 完整性检查

| 内部类型 | 中文含义 | 当前处理 |
| --- | --- | --- |
| `template_year_not_matched` | 模板年份未匹配 | 提醒 |
| `template_not_matched` | 未匹配到模板 | 提醒 |
| `template_multiple_matched` | 匹配到多个模板 | 使用最近模板并提醒 |
| `missing_section` | 疑似缺少章节 | 只按标题名比较，不按编号 |
| `empty_section_body` | 章节正文为空 | 检查当前标题与下一个标题之间的有效正文 |
| `placeholder_text_found` | 正文存在占位符 | 识别 `XX`、`XXX`、`TODO`、`待补充` 等 |
| `template_key_section_missing` | 模板缺少关键章节 | 无法比较时报警并要求检查模板标题样式 |
| `key_section_missing` | 待检 Word 缺少关键章节 | 相似度记为 0%，报警 |
| `key_section_similarity_low` | 关键章节相似度不足 | 文字相似度低于 95% 时报警 |
| `key_section_heading_no_changed` | 子章节编号不同 | 同名子章节的显式编号或相对结构编号不同 |
| `key_section_content_missing` | 模板内容缺失 | 列出模板有、待检 Word 没有的文本块 |
| `key_section_content_modified` | 章节内容不同 | 同一位置文本发生修改 |
| `key_section_content_added` | 章节新增内容 | 列出待检 Word 新增的文本块 |

关键章节比较是确定性文本 Diff，不调用向量模型。比较前只统一全角/半角和连续空白；所有实质差异均列出，95% 只决定是否额外产生相似度警告。模板是参考，不自动修改待检 Word。

## 5. 当前 API 分组

| 分组 | 主要接口 | 用途 |
| --- | --- | --- |
| 系统 | `GET /health` | 服务健康检查 |
| 访客身份 | 自动下发 `doc_agent_visitor` Cookie | 无需登录，隔离不同浏览器的业务记录 |
| Agent | `POST /agent/check`、`POST /agent/check/stream` | 统一处理文档校核、强条抽取和知识问答；表单 `mode` 区分前端模式 |
| 会话 | `GET/DELETE /agent/sessions...` | 会话列表、详情和删除 |
| 运行记录 | `GET/DELETE /agent/runs...` | Agent Trace 列表、详情和删除 |
| Word | `/word/upload`、`/word/check`、`/word/completeness-check` | 上传和两类检查 |
| Word 修改 | `POST /word/fix-consistency`、`GET /word/documents/{id}/download` | 一致性自动修订和副本下载 |
| Word 查询 | `/word/issues`、`/word/sections` | 问题和章节查询 |
| Excel | `/excel/ingest`、`/excel/clauses`、`/excel/standard-validity` | 标准库维护和查询 |
| 模板 | `/templates`、`/templates/upload` | 模板上传、列表、详情和删除 |
| 知识库 | `/knowledge/documents`、`/knowledge/query` | RAG 文件管理和问答 |

Agent 与 Word 接口会自动使用访客 Cookie 过滤数据；知识库、模板和 Excel 接口维护全局共享资料。系统不再使用 Bearer Token。

## 6. 已完成功能状态

| 功能 | 状态 | 说明 |
| --- | --- | --- |
| 匿名访客身份 | 已完成 | 签名 HttpOnly Cookie，默认保留 90 天，无需登录注册 |
| 会话列表、新建、继续和删除 | 已完成 | 按浏览器访客隔离，刷新后恢复 |
| 会话上下文与摘要 | 已完成 | JSONB 消息 + 阶段摘要 |
| Agent Planner/Tools/Final Answer | 已完成 | 工具注册表驱动 |
| Agent 流式输出 | 已完成 | SSE 输出到前端 |
| Word 本地解析 | 已完成 | 标题、正文、表格、引用、章节 |
| 依据与 Excel 一致性检查 | 已完成 | 已针对主要误报进行修正 |
| 正文与依据一致性检查 | 已完成 | 支持同段多引用和名称单独引用 |
| 编制依据归入依据范围 | 已完成 | 不再作为普通正文处理 |
| 模板库 | 已完成 | 批量上传、自动分类、持久化、展开、删除 |
| 标题缺失提醒 | 已完成 | 只比较标题名 |
| 章节正文为空检查 | 已完成 | 读取标题间正文 |
| 正文占位符检查 | 已完成 | 识别常见占位文本 |
| 三个关键章节模板差异检查 | 已完成 | 比较正文、子章节编号及新增/删除/修改位置，低于 95% 报警 |
| 通用知识库入库 | 已完成 | LlamaParse + 双向量 |
| 关键词/向量混合检索 | 已完成 | 固定 0.6/0.4 |
| 带引用的知识回答 | 已完成 | 回答和来源一起返回 |
| RAG 冒烟评测脚本 | 已完成 | 仅示例集，不是正式业务评测 |
| Vue 2.7 公共工作台 | 已完成 | 无登录、会话历史、三模式、附件、停止生成和结果面板；生产构建通过 |
| Vue 2.7 资料管理页 | 已完成 | 独立 5175 页面，只包含知识库、Word 模板和 Excel 标准库；生产构建通过 |
| Word 自动修改 | 已完成 | 外层 Agent Loop、单条 WordEditRun、累积 changes 记忆、细粒度工具调用、精确写回和轨迹持久化 |
| PDF 强条自动识别与抽取 | 已完成 | 单条 ClauseExtractionRun、三类证据自动判断、原生文字层/OCR 多级正文恢复、条与款级强制单元展开、检查/抽取/验证 Agent Loop、结果缓存和人工复核闭环 |
| 统一三模式对话框 | 已完成 | 文档校核、强条抽取和知识问答共用会话、SSE、输入区和历史列表 |
| 对话输入与结果面板交互 | 已完成 | 结果概览固定且列表独立滚动；紧凑附件卡、加号上传、上箭头发送、IME 组词保护、附件直发和同键停止已落地 |
| 统一用户回答排版 | 已完成 | 校核、完整性、RAG 和强条总结共用无表格的稳定 Markdown 规范；内部 Agent JSON 不受影响 |
| 正式 RAG 评测集 | 未完成 | 下一阶段核心目标 |

## 7. 当前边界与待补齐项

1. 会话、文档、检查、Word 修改和强条抽取任务按匿名访客过滤；知识库、Word 模板和 Excel 标准库是全局共享资料。
2. 清除 Cookie、使用另一浏览器或更换设备会获得新的访客身份，旧会话仍在数据库中但无法通过新 Cookie 找回。
3. RAG 当前只能通过示例问题验证流程，尚不能说明真实业务命中率和回答准确率。
4. Word 修改核心已有状态机和精确写回自动化测试；一致性、完整性、RAG 和会话等模块的自动化回归覆盖仍不足。
5. 自动修改当前只处理一致性检查的警告和高风险问题；完整性提醒、提示问题和人工确认式差异预览暂不自动修改。
6. Word Loop 的数据库状态、累计 `changes` 和 `decision_trace` 可以持久化审计，但 `latest_observation` 仍是进程内变量，服务中断后暂不支持自动断点续跑。
7. 强条版式识别依赖已配置的百炼视觉模型；正文优先复用缓存和 PDF 原生文字层，必要时再依赖 LlamaParse。视觉调用失败、条/款引用无法定位或 OCR 质量过低时会进入人工复核。它不会自动把抽取结果写进 Excel 标准库。
8. 强条抽取会按文件哈希和解析/提示词版本复用已完成结果；算法升级时需同步提升版本号，避免读取旧缓存。
9. 两个前端的 `dist/`、上传文件、强条分页缓存、Milvus 数据和 Python 缓存属于运行产物，不应作为主要代码阅读对象。
10. 资料管理页当前只依赖网址入口隔离，知道 5175 地址或后端管理接口的人也能维护资料；这是已确认的低安全需求边界。
11. Vue 2 已停止官方维护；当前使用最终版 Vue 2.7.16 是既定技术要求，构建链依赖的安全告警需在生产部署前评估。

## 8. 后续目标

### 8.1 目标一：正式 RAG 评测集

优先级：最高。

计划交付：

1. 从真实通信设计查询任务中整理问题。
2. 每个问题标注标准答案要点、目标来源文件、目标页码或章节、关键词和不可回答边界。
3. 区分精确依据查询、概念问答、跨段总结、同义表达和负样本。
4. 评测 Recall@K、MRR、来源命中率、关键词命中率、引用正确率和答案要点覆盖率。
5. 记录关键词/向量权重、Top K、切块长度和提示词的调参结果。
6. 保留固定回归集，后续每次修改 RAG 都重新运行。

### 8.2 目标二：完善 Word 修改体验

当前一致性自动修改闭环已经完成。后续根据实际使用补充：

1. 修改前后差异预览和逐项确认。
2. 更多包含表格、超链接、域和复杂样式的 Word 回归样例。
3. 编辑失败项的人工处理入口。
4. 是否扩展到完整性问题由业务规则另行确认，当前明确不自动修改。

### 8.3 后续工程化目标

1. 根据使用量补充匿名访客数据过期清理策略。
2. 为一致性、完整性、RAG 和会话记忆增加自动化测试。
3. 增加报告导出、日志、监控和数据库备份。
4. 完成公网部署、HTTPS、生产环境密钥和上传大小限制。
5. 根据实际团队需求决定知识库继续共享，还是增加公共库与个人库两层权限。

## 9. 推荐学习顺序

按以下顺序阅读，可以先掌握整体，再进入业务规则：

1. `README.md`：了解项目能力和启动方式。
2. `backend/app/main.py`：看后端入口和路由分组。
3. `backend/app/db/models.py`：看系统保存了哪些数据。
4. `backend/app/routers/agent.py`：看前端请求如何进入 Agent。
5. `backend/app/agent/workflow.py`：看 Planner、工具和最终回答主流程。
6. `backend/app/agent/registry.py` 与 `tools.py`：看有哪些工具以及如何封装。
7. `backend/app/services/session_memory.py`：看会话上下文和摘要。
8. `backend/app/services/word_references.py`、`word_sections.py`、`section_scope.py`：看 Word 解析结果如何结构化。
9. `backend/app/services/word_check.py`：看一致性规则和优先级。
10. `backend/app/agent/workflow.py`、`word_edit_tools.py`、`backend/app/services/word_edit_workflow.py` 与 `word_editor.py`：看外层 Agent Loop、下一动作决策、单任务累积记忆、精确写回和复检闭环。
11. `backend/app/agent/clause_extraction_tools.py` 与 `backend/app/services/clause_extraction.py`：看强条抽取的单步工具、自动证据识别、任务记忆和结果复用。
12. `backend/app/services/template_ingest.py`、`key_section_diff.py` 与 `completeness_check.py`：看模板入库、三个关键章节文本 Diff 和完整性检查。
13. `backend/app/services/knowledge_base.py`、`keyword_embedding.py`、`embedding_qwen.py`、`knowledge_store.py`：看 RAG 全链路。
14. `backend/app/llm.py` 与各业务回答提示词：看统一用户回答排版如何与领域规则组合。
15. `backend/app/visitor.py`：看匿名 Cookie 如何映射为内部访客 ID。
16. `frontend-vue2/src/App.vue` 与 `Workspace.vue`：看公共工作台如何复用访客会话、三种模式和流式接口。
17. `frontend-vue2/src/components/`：按侧边栏、统一对话区、结果面板和安全 Markdown 渲染分别阅读。
18. `frontend-admin-vue2/src/App.vue`：看三个共享资料模块如何独立维护。

## 10. 文档维护原则

新增或移动源码后，应同步更新本文第一部分的代码树。完成功能后，应同步更新“已完成功能状态”；新增阶段目标时，应放入“后续目标”，不要继续保留已经失效的早期设计假设。
