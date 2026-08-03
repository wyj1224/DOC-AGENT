# DOC AGENT Vue 2 前端

这是无需登录的 Vue 2.7 公共工作台，复用 FastAPI、匿名访客 Cookie、REST 和 SSE 接口。

```bash
cd frontend-vue2
npm install
npm run dev
```

- 默认地址：`http://127.0.0.1:5174`
- 默认后端：`http://127.0.0.1:8000`
- 如需修改后端地址，复制 `.env.example` 为 `.env` 并修改 `VITE_API_BASE`。
- 知识库、Word 模板和 Excel 标准库维护已迁移到 `frontend-admin-vue2/`。
- 所有请求都携带后端自动签发的 HttpOnly 访客 Cookie，刷新后可恢复本浏览器的会话。
