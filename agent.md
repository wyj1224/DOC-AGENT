# 灵枢·规鉴后端代码地图

最后更新：2026-09-05。

当前后端是一个面向两种业务的通用 Agent Harness：

- `document_check`：自由 ReAct，完成 Word 一致性与完整性检查；
- `word_edit`：安全受限 ReAct，只选择可信问题 ID，确定性代码负责实际修改。

旧知识文档问答 RAG、Milvus 和 Embedding 已删除。现在的 Memory 是 PostgreSQL 中的 Experience Insight，不使用向量检索。

## 1. 核心执行流

```text
POST /agent/check
  -> workflow.agent_check
  -> prepare_session：恢复聊天历史与资源指针
  -> route_task：确定 document_check 或 word_edit
  -> create AgentTask
  -> harness.run_agent
       -> 任务开始时加载同 owner、同业务的 active Experience（最多 8 条）
       -> create AgentEpisode（最多 2 次）
       -> create Environment
       -> ReAct Loop
            observe: 读取数据库状态与上一条工具结果
            decide: LLM 返回一个 AgentAction JSON
            validate: Pydantic + allowed_actions
            act: 注入可信参数并调用一个工具
            observe: 保存结构化 ToolObservation
            log: 保存完整可观察 AgentStep
       -> 确定性 Evaluator 查询数据库/文件/工具事实
       -> success：结束 Task
       -> manual_review / terminal_failure：停止
       -> retryable_failure：Reflection -> candidate Experience -> Episode 2
       -> Episode 2 成功：candidate 变 active
       -> Episode 2 失败：candidate 变 retired，Task 为 terminal_failure
  -> 生成用户回答
  -> append_turn：更新聊天记录与结构化资源指针
```

这里的三层概念是：

- Harness：模型调用、循环、工具调度、日志、Evaluator、Retry 和 Memory 的通用运行设施；
- Workflow：会话、任务分类和两个业务分支组成的产品流程；
- ReAct：每个 Episode 内部反复执行 observe → decide → act → observe 的决策方式。

## 2. Agent 目录

### `backend/app/agent/contracts.py`

所有 LLM 边界的 Pydantic 结构：

- `AgentAction`：`call_tool / finish / manual_review`；
- `ToolObservation`：工具成功、结果或错误；
- `EvaluationResult`：四态裁决；
- `ReflectionResult`：失败事实、经验和重试策略；
- `parse_json_model()`：从模型文本解析并验证 JSON。

`BaseModel` 只验证结构是否合法，不判断业务是否真的完成。

### `backend/app/agent/harness.py`

通用运行器：

- `run_agent()`：控制最多两个 Episode；
- `build_messages()`：组装系统提示、业务提示、状态、聊天上下文、Experience 和 Retry Reflection；
- `validate_allowed()`：阻止模型跳过状态前置条件；
- `MAX_EPISODES = 2`：当前重试上限。

模型只提供简短 `reason_summary`，不保存或要求隐式 Chain-of-Thought。

### `backend/app/agent/environments.py`

Environment Adapter 把通用 Harness 接到不同业务：

- `DocumentCheckEnvironment`
  - ActionSet：一致性检查、完整性检查、问题查询、结束或转人工；
  - LLM 可自由决定调用顺序；Evaluator 检查必需工具是否齐全。
- `WordEditEnvironment`
  - ActionSet：`inspect -> prepare -> apply -> verify`；
  - LLM 只能选择观察中 `auto_fixable=true` 的 `issue_id`；
  - 文档 ID、用户 ID、定位、原文和替换值由确定性代码注入。
公共接口是 `start()`、`state()`、`allowed_actions()`、`trusted_args()`、`execute()`、`finish()`、`abort()`。

### `backend/app/agent/evaluators.py`

Evaluator 不相信 LLM 自己声称“完成”，会主动检查：

- 公共：异常、最大步数、终止动作；
- 文档检查：必需工具、文档所有权、解析状态、结果 document_id 一致；
- Word 修改：Run 状态、change 状态、输出文件、解析状态、复检记录；

四个状态：

- `success`：确定性事实证明完成；
- `retryable_failure`：换一个 Episode 可能修复，例如漏步骤、格式错误、临时工具错误；
- `manual_review`：继续自动执行不安全或证据不确定；
- `terminal_failure`：输入无效、越权、文件丢失、数据矛盾，或两个 Episode 都失败。

### `backend/app/agent/runtime_store.py`

持久化 `AgentTask / AgentEpisode / AgentStep`。每个 Step 保存：

- model input 与 raw model output；
- 结构化 action；
- 系统实际注入的 trusted args；
- observation；
- 执行前后状态；
- 状态、错误和耗时。

### `backend/app/agent/reflection.py`

`reflect_on_failure()` 只读取可观察轨迹和确定性 Evaluator 结论，总结失败经验。LLM 输出不合法时会使用确定性 fallback。

### `backend/app/agent/experience_memory.py`

- `load_active_experiences()`：任务开始时读取同一个 `owner_user_id + task_type` 的最近 8 条 active Insight；
- `create_candidate()`：Episode 1 可重试失败后创建候选经验；
- `activate_candidate()`：Episode 2 成功后保存成功原因并激活；
- `retire_candidate()`：Episode 2 未成功则退休，后续不会检索。

完整 Raw Trajectory 通过 `failed_episode_id/successful_episode_id` 保持可追溯；实际注入 Prompt 的只有精简 Insight。

### `backend/app/agent/workflow.py`

顶层产品入口：

- `route_task()`：用简单确定性关键词与请求 mode 区分文档检查和修改；
- `agent_check()`：创建会话/Task、选择 Environment、运行 Harness、生成回答并更新会话；
- `run_word_edit_loop()`：保留给现有 `/word/fix-consistency` 接口的薄适配器。

## 3. 工具与业务服务

### Word 上传与检查工具

`backend/app/agent/tools.py`：

- `parse_word_tool`：由 `/word/upload` 调用，先把 Word 转成可信数据库资源；不进入 Agent 的 ActionSet；
- `word_check_tool`
- `completeness_check_tool`
- `get_issues_tool`

### Word 修改工具

`backend/app/agent/word_edit_tools.py`：

- `inspect_consistency_issues_tool`
- `prepare_word_edit_tool`
- `apply_word_edit_tool`
- `verify_word_edit_tool`

实际状态机和安全写回位于：

- `services/word_edit_workflow.py`
- `services/word_editor.py`
- `services/word_check.py`

## 4. 会话与 Memory 的区别

`services/session_memory.py` 管理当前聊天：

- 保存用户和助手消息，用于理解“这个文档”“继续修改”等指代；
- 12 条未摘要消息触发压缩，保留最近 6 条；
- `active_document_id`、`active_edit_run_id`、`last_task_id`、`last_episode_id` 单独保存，不依赖自然语言摘要恢复关键资源。

Experience Memory 管理跨任务经验：

- 新 Task 开始时读取 active Insight；
- Task 内 Retry 直接使用刚生成的 Reflection，不再重新查询数据库；
- 不同 owner 的经验互不可见。

## 5. 数据库模型

`backend/app/db/models.py` 中与 Harness 直接相关的表：

- `AgentSession`：聊天记录、摘要和资源指针；
- `AgentTask`：一次用户目标；
- `AgentEpisode`：同一任务的一次完整尝试；
- `AgentStep`：一次 action/observation 状态转换；
- `AgentExperience`：由失败和纠正结果验证过的经验。

业务记录保持独立：

- `CheckRun`：文档检查事实；
- `WordEditRun`：Word 修改事实；
两个业务 Run 都可通过 `task_id/episode_id` 回到 Agent 轨迹。`CheckRun` 不再同时承担“用户任务”和“检查事实”两个概念。

## 6. API

主要入口：

```text
POST /agent/check
POST /agent/check/stream
GET  /agent/sessions
GET  /agent/tasks
GET  /agent/tasks/{task_id}
GET  /agent/experiences
```

`GET /agent/tasks/{task_id}` 返回 Episode、Evaluation、Reflection 和 Step 级可观察轨迹，适合调试与面试演示。

原来的 `/agent/runs` 仍保留用于查看 `CheckRun` 业务记录。知识问答 `/knowledge/*` 已删除。

## 7. 当前安全边界

- LLM 不能直接提供 owner、文件路径、数据库主键、定位或替换事实；
- Pydantic 拒绝格式不合法的模型输出；
- allowed_actions 拒绝越过当前业务状态的动作；
- Evaluator 主动查询数据库和文件，不让执行模型自我裁决；
- 自动修改只作用于明确可定位、可审计的 consistency issue；
- 证据不确定时进入 `manual_review`，不会为了自动完成而编造结果；
- 最大 Episode 数为 2，最大 Step 数按 Environment 单独设置。

## 8. 验证

```bash
cd backend
ruff check app tests
python -m pytest -q -p no:cacheprovider
python -m app.cli.init_db
```

本地数据库由 `backend/docker-compose.yml` 提供 PostgreSQL 16。生产环境应将 `init_db()` 中的兼容式 DDL 改为 Alembic migration。
