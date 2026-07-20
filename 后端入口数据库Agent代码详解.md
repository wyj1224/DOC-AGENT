# 后端入口、数据库与 Agent 代码详解

这份文档专门解释当前改动比较大的三块代码：

- `backend/app/main.py`：FastAPI 后端入口，定义所有 HTTP 接口。
- `backend/app/db/database.py` 和 `backend/app/db/models.py`：数据库连接、建表、表结构。
- `backend/app/agent/registry.py`、`backend/app/agent/tools.py`、`backend/app/agent/workflow.py`：Agent 工具注册、工具执行、LLM 规划和报告生成。

可以按下面顺序读：

```text
main.py
  -> 接收前端/Postman 请求
  -> 调用 tools 或 workflow

tools.py
  -> 把 Word 解析、Word 检查、问题查询包装成工具函数

registry.py
  -> 把工具函数登记成 Agent 可调用工具

workflow.py
  -> planner 让 LLM 规划工具
  -> execute_tools 执行工具
  -> final_answer 让 LLM 生成报告
  -> check_runs 记录本次 Agent 任务

models.py / database.py
  -> 存 Excel 标准库、Word 引用、检查问题、Agent 任务记录
```

---

## 1. `main.py`：后端总入口

文件路径：

```text
backend/app/main.py
```

这个文件负责把后端能力暴露成 HTTP 接口。前端、Postman 都是通过这里调用后端。

### 1.1 import 部分

```python
from pathlib import Path
import shutil
from datetime import date
```

- `Path`：处理文件路径，比字符串拼接更稳。
- `shutil`：用于保存上传文件，比如把 Postman 上传的 Excel/Word 写到本地。
- `date`：把前端传来的 `publish_date` 字符串转成日期对象。

```python
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
```

- `FastAPI`：创建后端应用。
- `File`：声明接口接收上传文件。
- `Form`：声明接口接收表单字段。
- `HTTPException`：主动返回 HTTP 错误，比如用户上传了非 `.docx`。
- `UploadFile`：FastAPI 对上传文件的封装。
- `CORSMiddleware`：允许前端跨域访问后端。

```python
from app.agent.tools import get_issues_tool, parse_word_tool, word_check_tool
from app.agent.workflow import agent_check
```

- `parse_word_tool`：解析 Word，抽取引用。
- `word_check_tool`：执行 Word 检查。
- `get_issues_tool`：查询检查问题。
- `agent_check`：完整 Agent 流程，包含 planner、工具执行、最终报告。

```python
from app.config import BACKEND_ROOT
from app.db.database import SessionLocal, init_db
from app.db.models import CheckRun, MandatoryClause, StandardValidityRecord
from app.services.excel_ingest import ingest_excel_to_postgres
```

- `BACKEND_ROOT`：后端根目录，用于拼接上传文件保存路径。
- `SessionLocal`：创建数据库会话，用来查询数据库。
- `init_db`：启动时自动建表/补字段。
- `CheckRun`：Agent 任务记录表。
- `MandatoryClause`：强制性条文库表。
- `StandardValidityRecord`：标准有效性/替代表。
- `ingest_excel_to_postgres`：Excel 入库逻辑。

### 1.2 创建 FastAPI app

```python
app = FastAPI(title="Clause Agent API")
```

创建后端应用，接口文档里显示的标题是 `Clause Agent API`。

### 1.3 CORS 跨域配置

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

这是为前端准备的。

如果以后前端用 Vite，默认端口通常是 `5173`。浏览器会限制前端访问不同端口的后端，所以这里明确允许：

```text
http://127.0.0.1:5173
http://localhost:5173
```

含义：

- `allow_origins`：允许哪些前端地址访问后端。
- `allow_credentials=True`：允许带 cookie 或认证信息，后续做登录会用到。
- `allow_methods=["*"]`：允许 GET、POST 等所有请求方法。
- `allow_headers=["*"]`：允许所有请求头。

### 1.4 上传目录

```python
UPLOAD_ROOT = BACKEND_ROOT / "data" / "uploads"
```

统一规定上传文件保存到：

```text
backend/data/uploads
```

Excel 会放到：

```text
backend/data/uploads/excel
```

Word 会放到：

```text
backend/data/uploads/word
```

### 1.5 启动时初始化数据库

```python
@app.on_event("startup")
def startup():
    init_db()
```

FastAPI 启动时自动执行 `init_db()`。

作用：

- 如果表不存在，就创建表。
- 如果旧表缺少新字段，就补字段。
- 如果索引不存在，就创建索引。

所以现在不一定每次都需要手动执行：

```bash
python -m app.cli.init_db
```

不过如果数据库刚启动、或者你想确认表结构，可以手动跑一次。

### 1.6 健康检查接口

```python
@app.get("/health")
def health():
    return {"status": "ok"}
```

用于确认后端是否启动成功。

测试：

```text
GET http://127.0.0.1:8000/health
```

正常返回：

```json
{"status": "ok"}
```

### 1.7 Excel 入库接口

```python
@app.post("/excel/ingest")
def ingest_excel(
    file: UploadFile = File(...),
    sheet: str = Form("强条"),
    replace: bool = Form(True),
):
```

接口：

```text
POST /excel/ingest
```

接收三个字段：

- `file`：上传的 Excel 文件。
- `sheet`：要读取的 sheet 名，默认是 `强条`。
- `replace`：是否覆盖旧数据，默认 `true`。

```python
upload_dir = UPLOAD_ROOT / "excel"
upload_dir.mkdir(parents=True, exist_ok=True)
```

创建 Excel 上传目录：

```text
backend/data/uploads/excel
```

`parents=True` 表示父目录不存在也一起创建。

`exist_ok=True` 表示目录已存在也不报错。

```python
file_path = upload_dir / Path(file.filename).name
with file_path.open("wb") as out:
    shutil.copyfileobj(file.file, out)
```

把上传的 Excel 文件保存到本地。

`Path(file.filename).name` 只取文件名，不带用户本地路径，避免路径混乱。

```python
result = ingest_excel_to_postgres(str(file_path), sheet=sheet, replace=replace)
```

调用 Excel 入库服务。

这个服务会读取 Excel，然后写入两类库：

- `mandatory_clauses`：强制性条文库。
- `standard_validity_records`：标准有效性/替代关系库。

```python
return {
    "file_name": file.filename,
    "sheet": sheet,
    "replace": replace,
    **result,
}
```

返回入库结果。

`**result` 表示把服务返回的字典展开合并进响应。

### 1.8 查询强条库

```python
@app.get("/excel/clauses")
def list_excel_clauses():
```

接口：

```text
GET /excel/clauses
```

作用：

查看 Excel 入库后的强条数据是否完整。

```python
with SessionLocal() as session:
```

创建数据库会话。

`with` 的好处是代码块结束后自动关闭 session。

```python
clauses = session.query(MandatoryClause).order_by(MandatoryClause.row_index, MandatoryClause.id).all()
```

查询所有强条记录。

排序逻辑：

1. 先按 Excel 行号 `row_index` 排。
2. 再按数据库主键 `id` 排。

这样返回顺序尽量接近 Excel 原始顺序。

返回字段包括：

- `standard_no`：标准号。
- `standard_name`：标准名。
- `category`：标准分类。
- `applicable_scope`：适用范围。
- `mandatory_type`：强条类型，比如 `条文`、`全文`、`标准依据`。
- `clause_no`：条号。
- `clause_text`：条文内容。
- `chunk_text`：最终用于入库/检索的一整段文本。
- `source_file`：来源 Excel。
- `sheet_name`：来源 sheet。

### 1.9 查询标准有效性库

```python
@app.get("/excel/standard-validity")
def list_standard_validity():
```

接口：

```text
GET /excel/standard-validity
```

作用：

查看标准替代关系。

查询的是：

```python
StandardValidityRecord
```

核心字段：

- `old_standard_text`：旧标准文本。
- `new_standard_text`：新标准文本。
- `new_publish_date`：新标准发布日期。
- `new_effective_date`：新标准实施日期。
- `involved_content`：涉及内容，例如设计说明、图纸等。
- `note`：备注。
- `source_url`：来源链接。

后续判断“某个 Word 引用的是不是旧标准”主要依赖这张表。

### 1.10 Word 上传解析接口

```python
@app.post("/word/upload")
def upload_word(file: UploadFile = File(...)):
```

接口：

```text
POST /word/upload
```

作用：

上传 Word，解析 Word，抽取所有标准引用，写入 `word_documents` 和 `word_references`。

```python
if Path(file.filename).suffix.lower() != ".docx":
    raise HTTPException(status_code=400, detail="当前本地解析只支持 .docx 文件")
```

当前只支持 `.docx`。

如果用户上传 `.doc`、`.pdf`、`.wps`，直接返回 400。

```python
upload_dir = UPLOAD_ROOT / "word"
upload_dir.mkdir(parents=True, exist_ok=True)
```

创建 Word 上传目录。

```python
file_path = upload_dir / Path(file.filename).name
with file_path.open("wb") as out:
    shutil.copyfileobj(file.file, out)
```

把 Word 保存到本地。

```python
return parse_word_tool(file_path=str(file_path))
```

调用工具 `parse_word_tool`。

这个工具会：

1. 创建 `word_documents` 记录。
2. 解析 docx。
3. 抽取标准引用。
4. 写入 `word_references`。
5. 返回 `document_id`、`reference_count`、引用列表等。

### 1.11 Word 检查接口

```python
@app.post("/word/check")
def check_word(
    document_id: int = Form(...),
    publish_date: str = Form(""),
    replace: bool = Form(True),
    issue_limit: int = Form(50),
):
```

接口：

```text
POST /word/check
```

作用：

不经过 LLM，直接执行规则检查。

参数：

- `document_id`：要检查哪个 Word。
- `publish_date`：设计文件发布日期，可为空。
- `replace`：是否覆盖该文档旧的检查问题。
- `issue_limit`：最多返回多少条问题。

```python
parsed_publish_date = date.fromisoformat(publish_date) if publish_date else None
```

如果传了 `publish_date`，就把字符串转成 `date`。

格式必须类似：

```text
2024-04-10
```

```python
return word_check_tool(...)
```

调用 `word_check_tool`。

这个工具会统一执行：

- `basis_excel`：设计依据 vs Excel 标准库。
- `body_basis`：正文引用 vs 1.2 设计依据。

最终问题写入：

```text
check_issues
```

### 1.12 查询 Word 问题接口

```python
@app.get("/word/issues")
def get_word_issues(
    document_id: int,
    check_scope: str = "",
    issue_type: str = "",
    severity: str = "",
    issue_limit: int = 50,
):
```

接口：

```text
GET /word/issues
```

作用：

从数据库查询已经检查出来的问题。

参数：

- `document_id`：必填。
- `check_scope`：可选，区分检查范围。
- `issue_type`：可选，按问题类型筛选。
- `severity`：可选，按严重程度筛选。
- `issue_limit`：可选，返回数量限制。

常用查询：

```text
GET /word/issues?document_id=20&check_scope=basis_excel&issue_limit=0
GET /word/issues?document_id=20&check_scope=body_basis&issue_limit=0
```

`issue_limit=0` 表示不限制数量，返回全部。

### 1.13 Agent 检查接口

```python
@app.post("/agent/check")
def check_with_agent(
    message: str = Form("请全面检查这个文档有没有问题"),
    document_id: int | None = Form(None),
    publish_date: str = Form(""),
    file: UploadFile | None = File(None),
):
```

接口：

```text
POST /agent/check
```

这是当前最像 Agent 的入口。

它接收：

- `message`：用户自然语言问题。
- `document_id`：已有 Word 文档 ID。
- `publish_date`：设计文件发布日期。
- `file`：也可以直接上传 Word。

两种用法：

```text
先 /word/upload，拿 document_id，再 /agent/check
```

或者：

```text
直接 /agent/check 上传 file
```

代码逻辑：

```python
file_path = ""
if file:
    ...
    file_path = str(saved_path)
```

如果用户传了 Word 文件，就保存文件，并把路径传给 Agent。

```python
parsed_publish_date = date.fromisoformat(publish_date) if publish_date else None
```

把发布日期字符串转成日期。

```python
return agent_check(...)
```

进入 Agent Workflow。

返回结果包含：

- `run_id`：本次 Agent 任务记录 ID。
- `tool_plan`：LLM 规划的工具调用步骤。
- `tool_results`：工具执行结果。
- `answer`：LLM 生成的最终报告。

### 1.14 Agent 任务记录列表

```python
@app.get("/agent/runs")
def list_agent_runs(document_id: int | None = None, limit: int = 20):
```

接口：

```text
GET /agent/runs
```

作用：

查看历史 Agent 检查任务。

可选参数：

- `document_id`：只看某个 Word 的历史任务。
- `limit`：最多返回多少条，默认 20。

```python
query = session.query(CheckRun)
if document_id:
    query = query.filter(CheckRun.document_id == document_id)
```

如果传了 `document_id`，就只查这个文档的任务。

```python
runs = query.order_by(CheckRun.id.desc()).limit(limit).all()
```

按 `id` 倒序，最新任务排前面。

返回的是摘要，不包含完整 tool_results。

### 1.15 Agent 单次任务详情

```python
@app.get("/agent/runs/{run_id}")
def get_agent_run(run_id: int):
```

接口：

```text
GET /agent/runs/{run_id}
```

作用：

查看某一次 Agent 任务的完整 trace。

如果找不到：

```python
raise HTTPException(status_code=404, detail="check run not found")
```

正常返回：

- `run_id`
- `document_id`
- `status`
- `issue_count`
- `duration_ms`
- `user_message`
- `tool_plan`
- `tool_results`
- `answer`
- `error_message`

### 1.16 `check_run_summary`

```python
def check_run_summary(check_run: CheckRun) -> dict[str, object]:
```

把数据库里的 `CheckRun` ORM 对象转成接口返回的字典。

这里只返回摘要字段：

- `run_id`
- `document_id`
- `status`
- `issue_count`
- `duration_ms`
- `started_at`
- `finished_at`
- `user_message`

### 1.17 `check_run_detail`

```python
def check_run_detail(check_run: CheckRun) -> dict[str, object]:
```

在摘要基础上增加完整内容：

- `tool_plan`
- `tool_results`
- `answer`
- `error_message`

这里用了：

```python
return {
    **check_run_summary(check_run),
    ...
}
```

`**check_run_summary(check_run)` 表示先把摘要字典展开，然后再补充详情字段。

---

## 2. `database.py`：数据库连接与初始化

文件路径：

```text
backend/app/db/database.py
```

这个文件只做三件事：

1. 创建数据库 engine。
2. 创建数据库 session 工厂。
3. 初始化数据库表和索引。

### 2.1 import

```python
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
```

- `create_engine`：创建数据库连接引擎。
- `text`：执行原生 SQL。
- `sessionmaker`：创建数据库会话工厂。

```python
from app.config import get_settings
```

读取 `.env` 里的配置。

### 2.2 `get_engine`

```python
def get_engine():
    return create_engine(get_settings().database_url, pool_pre_ping=True)
```

作用：

根据 `.env` 里的 `DATABASE_URL` 创建数据库 engine。

`pool_pre_ping=True` 的意思是：

每次从连接池拿连接时先检查连接是否有效，避免数据库连接断开后直接报错。

当前默认数据库地址在 `config.py` 中：

```text
postgresql+psycopg://clause_agent:clause_agent@localhost:5432/clause_agent
```

### 2.3 `SessionLocal`

```python
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
```

这是一个“数据库会话工厂”。

后面代码里经常这样用：

```python
with SessionLocal() as session:
    ...
```

`session` 可以理解为一次数据库操作上下文。

常见操作：

```python
session.add(...)
session.query(...)
session.commit()
session.flush()
session.get(...)
```

### 2.4 `init_db`

```python
def init_db() -> None:
    from app.db.models import Base
```

导入 `Base`。

`Base` 记录了所有 ORM 表模型。

```python
engine = get_engine()
Base.metadata.create_all(bind=engine)
```

根据 `models.py` 中定义的表模型创建数据库表。

如果表已经存在，不会重复创建。

```python
with engine.begin() as connection:
```

开启一个数据库事务，用于执行原生 SQL。

这里主要是为了兼容旧数据库。

```python
connection.execute(text("ALTER TABLE check_issues ADD COLUMN IF NOT EXISTS ..."))
```

这些 SQL 的作用：

如果旧的 `check_issues` 表缺少字段，就自动补上。

目前补的字段包括：

- `section_title`
- `paragraph_index`
- `standard_no`
- `standard_name`
- `clause_no`
- `check_scope`

```python
connection.execute(text("CREATE INDEX IF NOT EXISTS ..."))
```

创建索引。

索引用于提升查询速度。

当前索引：

- `ix_check_issues_document_paragraph`
- `ix_check_issues_document_scope`
- `ix_check_runs_document_status`

---

## 3. `models.py`：数据库表结构

文件路径：

```text
backend/app/db/models.py
```

这个文件定义了 PostgreSQL 里的表。

SQLAlchemy ORM 的基本写法是：

```python
class 表名(Base):
    __tablename__ = "真实数据库表名"
    字段名: Mapped[类型] = mapped_column(...)
```

### 3.1 Base

```python
class Base(DeclarativeBase):
    pass
```

所有表模型都继承 `Base`。

`Base.metadata.create_all()` 会根据所有继承 `Base` 的类创建表。

### 3.2 TimestampMixin

```python
class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

这是一个公共时间字段类。

哪个表继承它，哪个表就自动有：

- `created_at`：创建时间。
- `updated_at`：更新时间。

`server_default=func.now()` 表示默认值由数据库生成。

`onupdate=func.now()` 表示更新时自动刷新更新时间。

### 3.3 User

```python
class User(Base, TimestampMixin):
    __tablename__ = "users"
```

用户表。

当前还没真正做登录，但已经为后续用户隔离预留。

字段：

```python
id
username
display_name
```

- `id`：用户主键。
- `username`：用户名，唯一。
- `display_name`：显示名称。

后面很多表都有：

```python
owner_user_id
```

这就是为多用户隔离预留的。

### 3.4 MandatoryClause

```python
class MandatoryClause(Base, TimestampMixin):
    __tablename__ = "mandatory_clauses"
```

强制性条文库。

来源：

```text
Excel 的“强条”sheet
```

这张表用于判断：

- Word 里引用的标准是否存在。
- 条号是否存在。
- 条文内容是否有匹配基础。

核心字段：

```python
standard_no
standard_name
category
applicable_scope
mandatory_count
mandatory_type
clause_no
clause_text
chunk_text
source_file
sheet_name
row_index
```

字段解释：

| 字段 | 含义 |
|---|---|
| `standard_no` | 标准号，例如 `GB/T 50010-2010` |
| `standard_name` | 标准名，例如 `混凝土结构设计标准` |
| `category` | 标准分类，例如国家标准、行业标准 |
| `applicable_scope` | 适用范围 |
| `mandatory_count` | Excel 里的强条数量字段 |
| `mandatory_type` | 当前记录类型，例如条文、全文、标准依据 |
| `clause_no` | 条号，例如 `11.3.1` |
| `clause_text` | 条文原文 |
| `chunk_text` | 拼好的文本块，后续可用于 RAG / 向量化 |
| `source_file` | 来源 Excel 文件 |
| `sheet_name` | 来源 sheet |
| `row_index` | Excel 行号 |

索引：

```python
Index("ix_mandatory_clauses_standard_clause", "standard_no", "clause_no")
Index("ix_mandatory_clauses_type", "mandatory_type")
```

第一个索引用于快速按标准号和条号查强条。

第二个索引用于按 `mandatory_type` 查询，比如查全文强条。

### 3.5 StandardValidityRecord

```python
class StandardValidityRecord(Base, TimestampMixin):
    __tablename__ = "standard_validity_records"
```

标准有效性库/替代关系库。

来源：

```text
Excel 的“清单”sheet 或标准替代清单部分
```

这张表用于判断：

- Word 里引用的是不是旧标准。
- 旧标准是否已经被新标准替代。
- 新标准什么时候发布、什么时候实施。

核心字段：

| 字段 | 含义 |
|---|---|
| `old_standard_text` | 旧标准完整文本 |
| `new_standard_text` | 新标准完整文本 |
| `new_publish_date` | 新标准发布日期 |
| `new_effective_date` | 新标准实施日期 |
| `involved_content` | 涉及内容 |
| `verified_date` | 核实时间 |
| `note` | 备注 |
| `source_url` | 来源链接 |
| `source_file` | 来源 Excel |
| `sheet_name` | 来源 sheet |
| `row_index` | Excel 行号 |

索引：

```python
Index("ix_standard_validity_effective_date", "new_effective_date")
```

用于按新标准实施日期查询。

### 3.6 WordDocument

```python
class WordDocument(Base, TimestampMixin):
    __tablename__ = "word_documents"
```

Word 文档表。

每上传一个 Word，就生成一条 `word_documents` 记录。

字段：

| 字段 | 含义 |
|---|---|
| `id` | 文档 ID |
| `owner_user_id` | 所属用户，暂时可空 |
| `file_name` | Word 文件名 |
| `declared_publish_date` | 设计文件发布日期 |
| `parse_status` | 解析状态，例如 pending、parsing、parsed |

```python
references: Mapped[list["WordReference"]] = relationship(back_populates="document")
```

表示：

一个 WordDocument 可以对应多条 WordReference。

也就是：

```text
一个 Word 文件 -> 多条标准引用
```

### 3.7 WordReference

```python
class WordReference(Base, TimestampMixin):
    __tablename__ = "word_references"
```

Word 引用表。

这张表保存从 Word 中抽出来的所有标准引用。

字段：

| 字段 | 含义 |
|---|---|
| `id` | 引用 ID |
| `document_id` | 属于哪个 Word |
| `file_name` | 来源文件名 |
| `section_title` | 所在章节标题 |
| `paragraph_index` | 所在段落序号 |
| `standard_no` | 抽取出的标准号 |
| `standard_name` | 抽取出的标准名 |
| `clause_no` | 抽取出的条号 |
| `quoted_text` | 引用原文 |
| `context` | 上下文 |

这张表非常关键。

后续检查基本都是拿它跟 Excel 库做对比。

索引：

```python
Index("ix_word_references_standard_clause", "standard_no", "clause_no")
Index("ix_word_references_file_paragraph", "file_name", "paragraph_index")
```

用于按标准号/条号查引用，以及按文件/段落定位引用。

### 3.8 CheckIssue

```python
class CheckIssue(Base, TimestampMixin):
    __tablename__ = "check_issues"
```

检查问题表。

每发现一个问题，就写一条 `check_issues`。

字段：

| 字段 | 含义 |
|---|---|
| `id` | 问题 ID |
| `document_id` | 属于哪个 Word |
| `word_reference_id` | 对应哪条 Word 引用 |
| `matched_clause_id` | 匹配到的强条 ID |
| `matched_standard_record_id` | 匹配到的标准替代记录 ID |
| `section_title` | 问题所在章节 |
| `paragraph_index` | 问题所在段落 |
| `standard_no` | 问题涉及的标准号 |
| `standard_name` | 问题涉及的标准名 |
| `clause_no` | 问题涉及的条号 |
| `check_scope` | 检查范围 |
| `issue_type` | 问题类型 |
| `severity` | 严重程度 |
| `original_text` | Word 原文 |
| `reason` | 问题原因 |
| `suggestion` | 修改建议 |

`check_scope` 当前主要有两类：

| check_scope | 含义 |
|---|---|
| `basis_excel` | 1.2 设计依据 vs Excel 标准库 |
| `body_basis` | 正文引用 vs 1.2 设计依据 |

常见 `issue_type`：

| issue_type | 含义 |
|---|---|
| `standard_replaced` | 标准已被替代 |
| `standard_name_mismatch` | 标准号匹配，但标准名不一致 |
| `standard_no_mismatch` | 标准名匹配，但标准号不一致 |
| `standard_not_found` | 标准号和标准名都没命中 |
| `body_reference_replaced_by_basis` | 正文仍引用旧标准，但 1.2 已列新标准 |
| `body_standard_no_mismatch` | 正文和 1.2 标准名能对上，但标准号不一致 |
| `body_standard_name_mismatch` | 正文和 1.2 标准号能对上，但标准名不一致 |
| `basis_declared_but_unused` | 1.2 里列了，但正文没用 |
| `body_reference_not_in_basis` | 正文引用了，但 1.2 没列 |

`severity` 当前常见：

| severity | 含义 |
|---|---|
| `high` | 高风险 |
| `warning` | 警告 |
| `info` | 提示 |

索引：

```python
Index("ix_check_issues_type_severity", "issue_type", "severity")
Index("ix_check_issues_document_paragraph", "document_id", "paragraph_index")
Index("ix_check_issues_document_scope", "document_id", "check_scope")
```

用于快速按问题类型、严重程度、文档、章节范围查询。

### 3.9 CheckRun

```python
class CheckRun(Base, TimestampMixin):
    __tablename__ = "check_runs"
```

Agent 任务记录表。

它不是直接给普通用户看的，而是用于：

- 调试。
- 复现。
- 审计追踪。
- 面试时展示 Agent trace。

字段：

| 字段 | 含义 |
|---|---|
| `id` | 本次 Agent 任务 ID |
| `document_id` | 检查哪个 Word |
| `user_message` | 用户原始问题 |
| `tool_plan` | LLM planner 输出的工具计划 |
| `tool_results` | 后端执行工具后的结果 |
| `answer` | LLM 最终报告 |
| `status` | running / success / failed |
| `error_message` | 失败原因 |
| `started_at` | 开始时间 |
| `finished_at` | 结束时间 |
| `duration_ms` | 耗时毫秒数 |
| `issue_count` | 本次发现问题数量 |

`tool_plan` 和 `tool_results` 是 JSON 字段。

这样可以直接保存结构化 trace。

---

## 4. `tools.py`：Agent 可调用工具

文件路径：

```text
backend/app/agent/tools.py
```

这个文件把业务能力封装成工具函数。

Agent 不直接操作数据库细节，而是调用这些工具。

### 4.1 公共上传目录

```python
UPLOAD_ROOT = BACKEND_ROOT / "data" / "uploads"
```

和 `main.py` 一样，规定上传文件保存根目录。

### 4.2 `parse_word_tool`

```python
def parse_word_tool(file_path: str | None = None, document_id: int | None = None) -> dict[str, object]:
```

作用：

解析 Word，抽取引用。

它有两种用法。

第一种：已有 `document_id`。

```python
if document_id:
    return get_document_parse_result(document_id)
```

如果已经解析过，就不重复解析，直接查数据库里的解析结果。

第二种：传入 `file_path`。

```python
source_path = Path(file_path)
upload_dir = UPLOAD_ROOT / "word"
upload_dir.mkdir(parents=True, exist_ok=True)
```

准备保存 Word 文件。

```python
with SessionLocal() as session:
    document = WordDocument(file_name=source_path.name, parse_status="parsing")
    session.add(document)
    session.commit()
    session.refresh(document)
```

创建一条 `WordDocument`。

这里先 `commit` 是为了拿到数据库生成的 `document.id`。

```python
saved_path = upload_dir / f"{document.id}_{source_path.name}"
```

最终保存路径会带上 document_id。

例如：

```text
backend/data/uploads/word/12_xxx.docx
```

这样可以避免同名文件互相覆盖。

```python
if source_path.resolve() != saved_path.resolve():
    shutil.copyfile(source_path, saved_path)
```

如果原文件路径不是目标路径，就复制过去。

```python
chunks = parse_docx_file(str(saved_path))
```

调用本地 Word 解析器。

这个函数在：

```text
backend/app/word_loader.py
```

它负责把 docx 解析成段落/标题等结构化 chunk。

```python
references = extract_references(chunks)
```

调用引用抽取逻辑。

这个函数在：

```text
backend/app/services/word_references.py
```

它会从 Word chunk 中抽出：

- 标准号。
- 标准名。
- 条号。
- 所在章节。
- 原文。
- 上下文。

```python
for item in references:
    reference = WordReference(...)
    session.add(reference)
    db_references.append(reference)
```

把抽取出的每条引用写入 `word_references`。

```python
document.parse_status = "parsed"
session.flush()
result = parse_result_dict(document, saved_path, len(chunks), db_references)
session.commit()
return result
```

解析完成后：

1. 把文档状态改成 `parsed`。
2. 组装返回结果。
3. 提交数据库事务。

### 4.3 `basis_excel_check_tool`

```python
def basis_excel_check_tool(document_id: int, replace: bool = True, issue_limit: int = 50, publish_date: date | None = None) -> dict[str, object]:
```

作用：

只做：

```text
1.2 设计依据 vs Excel 标准库
```

内部调用：

```python
check_word_document(..., check_scope="basis_excel")
```

目前这个工具没有放进 `TOOL_REGISTRY`，因为现在统一入口用的是 `word_check_tool`。

但它仍然可以作为后续拆分工具使用。

### 4.4 `body_basis_check_tool`

```python
def body_basis_check_tool(document_id: int, replace: bool = True, issue_limit: int = 50) -> dict[str, object]:
```

作用：

只做：

```text
正文引用 vs 1.2 设计依据
```

内部调用：

```python
check_word_document(..., check_scope="body_basis")
```

同样，目前没有注册给 LLM 单独调用。

### 4.5 `word_check_tool`

```python
def word_check_tool(document_id: int, replace: bool = True, issue_limit: int = 50, publish_date: date | None = None) -> dict[str, object]:
```

这是当前 Agent 主要使用的检查工具。

它统一执行：

```text
check_scope="all"
```

也就是两类检查都跑：

1. `basis_excel`
2. `body_basis`

调用：

```python
check_word_document(
    session,
    document_id=document_id,
    publish_date=publish_date,
    replace=replace,
    check_scope="all",
    issue_limit=issue_limit,
)
```

结果会写入 `check_issues`。

### 4.6 `get_issues_tool`

```python
def get_issues_tool(
    document_id: int,
    check_scope: str = "",
    issue_type: str = "",
    severity: str = "",
    issue_limit: int = 50,
) -> dict[str, object]:
```

作用：

查询 `check_issues`。

它支持按条件筛选：

```python
if check_scope:
    query = query.filter(CheckIssue.check_scope == check_scope)
if issue_type:
    query = query.filter(CheckIssue.issue_type == issue_type)
if severity:
    query = query.filter(CheckIssue.severity == severity)
```

所以可以查询：

```text
只看 basis_excel
只看 body_basis
只看 high
只看 standard_replaced
```

```python
issues = sorted(query.all(), key=issue_sort_key)
```

查出来之后按自定义优先级排序。

这个排序规则来自：

```text
backend/app/services/word_check.py
```

```python
returned_issues = issues if issue_limit <= 0 else issues[:issue_limit]
```

如果 `issue_limit <= 0`，返回全部。

否则只返回前 `issue_limit` 条。

### 4.7 `get_document_parse_result`

```python
def get_document_parse_result(document_id: int) -> dict[str, object]:
```

作用：

根据 `document_id` 查询已经解析过的 Word 引用。

如果 Agent 已经有 `document_id`，就可以直接读结果，不用重新解析 Word。

### 4.8 `parse_result_dict`

```python
def parse_result_dict(
    document: WordDocument,
    saved_path: Path | None,
    chunk_count: int,
    references: list[WordReference],
) -> dict[str, object]:
```

作用：

把数据库对象转成接口返回 JSON。

返回内容：

- `document_id`
- `file_name`
- `parse_status`
- `chunk_count`
- `reference_count`
- `references`
- `saved_path`

`references` 里每条引用包含：

- `reference_id`
- `section_title`
- `paragraph_index`
- `standard_no`
- `standard_name`
- `clause_no`
- `quoted_text`

---

## 5. `registry.py`：工具注册表

文件路径：

```text
backend/app/agent/registry.py
```

这个文件的作用是把工具统一登记起来。

以前工具调用可能写成：

```python
if tool_name == "parse_word_tool":
    ...
elif tool_name == "word_check_tool":
    ...
```

现在改成工具注册表：

```python
TOOL_REGISTRY = {
    "parse_word_tool": ToolSpec(...),
    "word_check_tool": ToolSpec(...),
    "get_issues_tool": ToolSpec(...),
}
```

这样更像一个 Agent 工具体系。

### 5.1 ToolSpec

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    func: Callable
    description: str
    args: str
```

`ToolSpec` 是一个工具说明结构。

字段：

| 字段 | 含义 |
|---|---|
| `name` | 工具名 |
| `func` | 真正执行的 Python 函数 |
| `description` | 工具说明 |
| `args` | 工具参数说明 |

`frozen=True` 表示创建后不希望被随便修改。

### 5.2 TOOL_REGISTRY

```python
TOOL_REGISTRY: dict[str, ToolSpec] = {
    ...
}
```

当前注册了三个工具：

| 工具 | 作用 |
|---|---|
| `parse_word_tool` | 解析 Word，抽取引用 |
| `word_check_tool` | 执行两类检查 |
| `get_issues_tool` | 查询检查问题 |

每个工具都有：

- `name`
- `func`
- `description`
- `args`

这使得后续新增工具很简单。

例如后面做完整性检查，可以加：

```python
"completeness_check_tool": ToolSpec(...)
```

做 RAG，也可以加：

```python
"rag_search_tool": ToolSpec(...)
```

### 5.3 `tool_prompt_text`

```python
def tool_prompt_text() -> str:
```

作用：

把工具注册表转换成给 LLM 看的 prompt 文本。

```python
for index, tool in enumerate(TOOL_REGISTRY.values(), start=1):
    lines.append(f"{index}. {tool.name}\n   参数：{tool.args}\n   作用：{tool.description}")
```

遍历所有工具，拼成类似：

```text
1. parse_word_tool
   参数：...
   作用：...

2. word_check_tool
   参数：...
   作用：...
```

这样 planner 不需要手写工具列表，而是自动从 registry 生成。

### 5.4 `run_tool`

```python
def run_tool(tool_name: str, args: dict[str, object]) -> dict[str, object]:
    return TOOL_REGISTRY[tool_name].func(**args)
```

作用：

根据工具名执行工具。

例如 LLM planner 输出：

```json
{"tool": "word_check_tool", "args": {"document_id": 20}}
```

后端执行：

```python
run_tool("word_check_tool", {"document_id": 20})
```

实际就是调用：

```python
word_check_tool(document_id=20)
```

---

## 6. `workflow.py`：Agent 工作流

文件路径：

```text
backend/app/agent/workflow.py
```

这是当前 Agent 的核心。

整体流程：

```text
agent_check
  -> create_check_run
  -> planner
  -> execute_tools
  -> final_answer
  -> finish_check_run
  -> return run_id + tool_plan + tool_results + answer
```

### 6.1 import

```python
import json
from datetime import date, datetime, timezone
```

- `json`：处理 LLM 输出 JSON，以及保存 JSON 字段。
- `date`：处理发布日期。
- `datetime`、`timezone`：记录 Agent 任务开始/结束时间。

```python
from openai import OpenAI
```

DeepSeek 使用 OpenAI 兼容接口，所以这里用 OpenAI SDK。

```python
from app.config import get_settings
from app.agent.registry import run_tool, tool_prompt_text
from app.db.database import SessionLocal
from app.db.models import CheckRun
```

- `get_settings`：读取 DeepSeek API Key、模型名等。
- `run_tool`：根据工具名执行工具。
- `tool_prompt_text`：生成工具说明 prompt。
- `SessionLocal`：写入 `check_runs`。
- `CheckRun`：Agent 任务记录表。

### 6.2 `planner`

```python
def planner(message: str, document_id: int | None = None, file_path: str = "") -> dict[str, object]:
```

作用：

让 LLM 根据用户问题生成工具调用计划。

输入：

- `message`：用户问题。
- `document_id`：如果已有 Word 文档 ID，就传它。
- `file_path`：如果是直接上传文件，就传文件路径。

核心 prompt：

```python
你是通信工程设计说明校核 Agent 的 planner。你要根据用户意图选择工具调用步骤，只能输出 JSON。
```

这句话限制 LLM：

只做规划，不要输出自然语言。

```python
可用工具：
{tool_prompt_text()}
```

工具说明来自 `registry.py`。

这样新增工具后，planner prompt 会自动更新。

```python
check_scope 可选：
- basis_excel：设计依据 vs Excel 标准库
- body_basis：正文引用 vs 1.2 设计依据
```

告诉 LLM 查询问题时怎么区分检查范围。

规则部分：

```text
- 如果没有 document_id 但有 file_path，第一步必须 parse_word_tool。
- 如果已有 document_id，不要调用 parse_word_tool。
- 如果用户要“检查/校核/报告/有没有问题”，必须调用 word_check_tool。
- 如果用户只关心设计依据，查询 basis_excel。
- 如果用户只关心正文、前后不一致、上下文冲突，查询 body_basis。
- 如果用户问“文档有没有问题/全面检查/生成报告”，两个 scope 都查询。
- 如果用户只想查看已有问题，可以只调用 get_issues_tool。
- 不要调用无关工具。
```

这些规则是 Agent planner 的核心。

它决定了：

- 什么时候解析 Word。
- 什么时候检查。
- 什么时候只查询已有问题。
- 查询哪一类问题。

最后：

```python
return parse_json(call_llm(prompt))
```

调用 LLM，然后把 LLM 返回的 JSON 字符串转成 Python 字典。

### 6.3 `execute_tools`

```python
def execute_tools(tool_plan: dict[str, object], publish_date: date | None = None) -> list[dict[str, object]]:
```

作用：

按照 planner 生成的计划逐步执行工具。

```python
results = []
current_document_id = None
```

- `results` 保存每一步工具执行结果。
- `current_document_id` 用于处理“先解析 Word，再检查 Word”的情况。

```python
for step in tool_plan["steps"]:
```

遍历 LLM 规划的每一步。

每一步通常长这样：

```json
{
  "tool": "word_check_tool",
  "args": {
    "document_id": 20,
    "replace": true,
    "issue_limit": 1
  }
}
```

```python
tool_name = step["tool"]
args = dict(step.get("args", {}))
```

取出工具名和参数。

```python
if current_document_id and "document_id" not in args:
    args["document_id"] = current_document_id
```

如果前一步解析 Word 得到了新的 `document_id`，后续工具没写 document_id，就自动补上。

```python
if current_document_id and "document_id" in args and not args["document_id"]:
    args["document_id"] = current_document_id
```

如果 LLM 写了：

```json
{"document_id": null}
```

也自动换成刚解析出来的 `document_id`。

```python
if tool_name == "word_check_tool":
    args["publish_date"] = publish_date
```

发布日期只给检查工具使用。

```python
result = run_tool(tool_name, args)
```

通过工具注册表执行工具。

```python
if tool_name == "parse_word_tool":
    current_document_id = result["document_id"]
```

如果当前工具是 Word 解析，就把解析出来的 document_id 保存下来。

```python
results.append({"tool": tool_name, "args": args, "result": result})
```

每一步工具执行结果都保存成 trace。

最终返回：

```python
[
  {
    "tool": "word_check_tool",
    "args": {...},
    "result": {...}
  },
  {
    "tool": "get_issues_tool",
    "args": {...},
    "result": {...}
  }
]
```

### 6.4 `final_answer`

```python
def final_answer(message: str, tool_results: list[dict[str, object]]) -> str:
```

作用：

让 LLM 根据工具结果生成最终中文报告。

它不是重新判断规则，而是总结工具返回的结构化结果。

prompt 要求：

```text
- 先给总览：发现多少问题。
- 按 check_scope 分成“设计依据 vs Excel”和“正文 vs 设计依据”。
- 优先说明 high / warning，info 类问题简单概括。
- 每个问题尽量说明章节标题、原文、原因、建议。
- 不要编造工具结果里没有的信息。
```

最后把工具结果放进去：

```python
工具结果 JSON：
{json.dumps(tool_results, ensure_ascii=False)}
```

`ensure_ascii=False` 是为了让中文不要变成 Unicode 编码。

例如避免变成：

```text
\u8bbe\u8ba1\u4f9d\u636e
```

### 6.5 `agent_check`

```python
def agent_check(
    message: str,
    document_id: int | None = None,
    file_path: str = "",
    publish_date: date | None = None,
) -> dict[str, object]:
```

这是 Agent 的总入口。

`main.py` 的 `/agent/check` 最终调用的就是它。

流程：

```python
started_at = datetime.now(timezone.utc)
run_id = create_check_run(document_id, message, started_at)
```

先创建一条 `check_runs` 记录，状态是 `running`。

```python
try:
    plan = planner(...)
    tool_results = execute_tools(...)
    answer = final_answer(...)
    issue_count = count_issues(tool_results)
    finish_check_run(...)
    return {...}
```

正常执行时：

1. LLM 规划工具。
2. 后端执行工具。
3. LLM 生成最终报告。
4. 统计问题数量。
5. 把任务记录改成 success。
6. 返回结果。

返回：

```python
{
    "run_id": run_id,
    "tool_plan": plan,
    "tool_results": tool_results,
    "answer": answer,
}
```

如果中间报错：

```python
except Exception as exc:
    finish_check_run(run_id, "failed", {}, [], "", str(exc), started_at, 0)
    raise
```

把 `check_runs` 状态改成 `failed`，并保存错误信息。

然后重新抛出异常，让 FastAPI 返回错误。

### 6.6 `create_check_run`

```python
def create_check_run(document_id: int | None, message: str, started_at: datetime) -> int:
```

作用：

创建一条 Agent 任务记录。

```python
check_run = CheckRun(
    document_id=document_id,
    user_message=message,
    started_at=started_at,
    status="running",
)
```

初始状态是：

```text
running
```

```python
session.add(check_run)
session.commit()
session.refresh(check_run)
return check_run.id
```

提交数据库，并返回新生成的 `run_id`。

### 6.7 `finish_check_run`

```python
def finish_check_run(...):
```

作用：

更新一条 Agent 任务记录。

成功和失败都通过它保存。

```python
finished_at = datetime.now(timezone.utc)
```

记录结束时间。

```python
check_run = session.get(CheckRun, run_id)
```

根据 `run_id` 找到对应任务。

然后写入：

```python
check_run.tool_plan = json_safe(plan)
check_run.tool_results = json_safe(tool_results)
check_run.answer = answer
check_run.status = status
check_run.error_message = error_message
```

保存 Agent trace 和最终报告。

```python
check_run.document_id = check_run.document_id or infer_document_id(tool_results)
```

如果一开始没有 document_id，比如用户直接在 `/agent/check` 上传文件，那么 document_id 是 `parse_word_tool` 执行后才产生的。

这里会从工具结果里补回 `document_id`。

```python
check_run.duration_ms = int((finished_at - started_at).total_seconds() * 1000)
```

计算耗时，单位毫秒。

```python
check_run.issue_count = issue_count
session.commit()
```

保存问题数量并提交数据库。

### 6.8 `count_issues`

```python
def count_issues(tool_results: list[dict[str, object]]) -> int:
```

作用：

从工具结果中统计问题数量。

优先看 `word_check_tool`：

```python
for item in tool_results:
    if item["tool"] == "word_check_tool":
        return int(item["result"].get("issue_count", 0))
```

因为 `word_check_tool` 是完整检查，最能代表本次总问题数。

如果没有 `word_check_tool`，就统计所有 `get_issues_tool` 的结果：

```python
return sum(...)
```

### 6.9 `infer_document_id`

```python
def infer_document_id(tool_results: list[dict[str, object]]) -> int | None:
```

作用：

从工具结果里推断本次任务对应哪个 Word。

它遍历所有工具结果：

```python
document_id = item["result"].get("document_id")
```

只要找到 document_id，就返回。

主要用于这种情况：

```text
/agent/check 直接上传 file，没有提前传 document_id
```

### 6.10 `json_safe`

```python
def json_safe(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))
```

作用：

把 Python 对象转换成可以写入 JSON 字段的对象。

为什么需要它？

因为 `tool_results` 里可能有：

- `date`
- `datetime`
- 其他不能直接写入 JSON 的对象

`default=str` 会把这些对象转成字符串。

### 6.11 `call_llm`

```python
def call_llm(prompt: str) -> str:
```

作用：

统一调用 LLM。

```python
settings = get_settings()
if not settings.llm_api_key:
    raise ValueError("请先在 backend/.env 中配置 DEEPSEEK_API_KEY")
```

先读取配置。

如果没有 DeepSeek API Key，就直接报错。

```python
client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
```

创建 OpenAI SDK 客户端。

这里虽然用的是 `OpenAI`，但实际可以调用 DeepSeek，因为 DeepSeek 提供 OpenAI 兼容接口。

```python
response = client.chat.completions.create(
    model=settings.llm_model,
    messages=[{"role": "user", "content": prompt}],
    temperature=0,
)
```

调用聊天模型。

`temperature=0` 表示尽量稳定输出，减少随机性。

```python
return response.choices[0].message.content.strip()
```

取出模型回复文本。

### 6.12 `parse_json`

```python
def parse_json(text: str) -> dict[str, object]:
```

作用：

把 LLM 返回的 JSON 文本转成 Python 字典。

因为 LLM 有时会返回：

```text
```json
{...}
```
```

所以先处理代码块：

```python
if text.startswith("```"):
    text = text.strip("`")
    text = text.removeprefix("json").strip()
```

然后截取第一个 `{` 到最后一个 `}`：

```python
return json.loads(text[text.find("{") : text.rfind("}") + 1])
```

这样即使 LLM 前后多输出了一点文字，也尽量只解析 JSON 部分。

---

## 7. 一次 `/agent/check` 的完整执行链路

假设你在 Postman 调用：

```text
POST http://127.0.0.1:8000/agent/check
```

form-data：

```text
message = 请全面检查这个文档有没有问题
document_id = 20
```

完整流程如下：

```text
1. main.py 接收 /agent/check 请求
2. 把 publish_date 转成 date
3. 调用 agent_check(message, document_id, file_path, publish_date)
4. workflow.py 创建 check_runs 记录，状态 running
5. planner 调用 LLM
6. LLM 返回 tool_plan
7. execute_tools 按 tool_plan 调用工具
8. run_tool 从 TOOL_REGISTRY 找到真实工具函数
9. word_check_tool 执行规则检查，写入 check_issues
10. get_issues_tool 查询指定 scope 的问题
11. final_answer 把工具结果交给 LLM 生成中文报告
12. finish_check_run 把 plan、results、answer、耗时、问题数写入 check_runs
13. /agent/check 返回 run_id、tool_plan、tool_results、answer
```

返回结构大概是：

```json
{
  "run_id": 3,
  "tool_plan": {
    "steps": []
  },
  "tool_results": [],
  "answer": "..."
}
```

其中：

- `run_id` 用于查询任务记录。
- `tool_plan` 用于看 LLM 怎么规划。
- `tool_results` 用于看每个工具返回了什么。
- `answer` 是最终给用户看的报告。

---

## 8. 当前接口总览

| 接口 | 方法 | 作用 |
|---|---|---|
| `/health` | GET | 检查后端是否启动 |
| `/excel/ingest` | POST | 上传 Excel，更新强条库和标准有效性库 |
| `/excel/clauses` | GET | 查看强条库 |
| `/excel/standard-validity` | GET | 查看标准有效性库 |
| `/word/upload` | POST | 上传 Word 并抽取引用 |
| `/word/check` | POST | 直接规则检查，不经过 Agent |
| `/word/issues` | GET | 查询检查问题 |
| `/agent/check` | POST | Agent 检查入口，返回 plan、tools、answer |
| `/agent/runs` | GET | 查询 Agent 任务记录列表 |
| `/agent/runs/{run_id}` | GET | 查询某次 Agent 任务详情 |

---

## 9. 当前数据库表总览

| 表 | 作用 |
|---|---|
| `users` | 用户表，暂时预留 |
| `mandatory_clauses` | 强制性条文库 |
| `standard_validity_records` | 标准替代/有效性库 |
| `word_documents` | Word 文档记录 |
| `word_references` | Word 中抽取出来的标准引用 |
| `check_issues` | 检查发现的问题 |
| `check_runs` | Agent 任务记录 / trace |

---

## 10. 当前 Agent 能力边界

现在已经有：

| 能力 | 状态 |
|---|---|
| 工具注册表 | 已有 |
| LLM planner | 已有 |
| 后端工具执行 | 已有 |
| LLM 报告生成 | 已有 |
| Agent trace / check_runs | 已有 |
| Word 本地解析 | 已有 |
| Excel 标准库入库 | 已有 |
| 设计依据 vs Excel | 已有 |
| 正文 vs 设计依据 | 已有 |

还没做或后续可做：

| 能力 | 说明 |
|---|---|
| 前端 | 可以开始做第一版 |
| RAG | 后续用于解释、适用性判断、问答 |
| 完整性检查 | 模板 Word vs 待检 Word |
| 用户登录 | 后续做用户隔离 |
| Critic 节点 | 后续做报告自检 |

---

## 11. 你明天读代码时建议顺序

建议不要从细节正则开始读，先按这个顺序：

```text
1. main.py
   先看接口怎么进来

2. agent/workflow.py
   看 Agent 怎么规划、执行、生成报告、记录 trace

3. agent/registry.py
   看工具怎么统一管理

4. agent/tools.py
   看工具实际做什么

5. db/models.py
   对照数据库表理解数据流

6. services/word_check.py
   最后再看具体检查规则

7. word_loader.py + services/word_references.py
   再看 Word 解析和引用抽取
```

如果只想理解当前主流程，先抓住这一条线：

```text
/agent/check
  -> agent_check
  -> planner
  -> execute_tools
  -> word_check_tool
  -> get_issues_tool
  -> final_answer
  -> check_runs
```

这条线理解了，整个后端就基本串起来了。
