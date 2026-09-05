# 灵枢·规鉴 Vue 2 统一前端

这是无需登录的 Vue 2.7 统一工作台，包含文档检查/修改 Agent、强条标准库管理和 Word 模板管理。

```bash
cd frontend-vue2
npm install
npm run dev
```

- 默认地址：`http://127.0.0.1:5174`
- 默认后端：`http://127.0.0.1:8000`
- 如需修改后端地址，复制 `.env.example` 为 `.env` 并修改 `VITE_API_BASE`。
- Agent 工作台：`http://127.0.0.1:5174/#/workspace`
- 资料管理：`http://127.0.0.1:5174/#/admin`
- 知识库问答与知识库管理已移除。
- 所有请求都携带后端自动签发的 HttpOnly 访客 Cookie，刷新后可恢复本浏览器的会话。
