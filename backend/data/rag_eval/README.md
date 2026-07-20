# RAG 检索测试集

每行一条 JSON，字段如下：

- `question`：用户问题；
- `expected_source`：期望命中的来源文件名；
- `expected_keywords`：前 `top_k` 个切块中必须出现的关键词。

先将 `smoke_knowledge.md` 上传到知识库，再执行：

```bash
cd backend
python -m app.cli.eval_rag data/rag_eval/questions.example.jsonl --top-k 5
```

正式测试集可以复制该结构，逐步加入标准号精确查询、同义问题、跨段落问题和无答案问题。
