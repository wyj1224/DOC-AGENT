"""OpenAI-compatible stand-in for DeepSeek, for load tests only.

    python scripts/loadtest/fake_llm.py --port 9100 --latency 2.0

Point the backend at it with DEEPSEEK_BASE_URL=http://127.0.0.1:9100.
Every call sleeps ``--latency`` seconds, then answers like a well-behaved agent:
call the first allowed tool, otherwise finish. Report and reflection prompts get
fixed, schema-valid replies. GET /stats reports call counts and peak concurrency.
"""

import argparse
import asyncio
import json
import time

import uvicorn
from fastapi import FastAPI, Request


app = FastAPI()
state = {"calls": 0, "active": 0, "peak": 0}
LATENCY_SECONDS = 2.0

REFLECTION = {
    "failure_code": "loadtest",
    "failure_stage": "loadtest",
    "failure_summary": "simulated failure",
    "lesson": "call the required tools before finishing",
    "retry_strategy": "call the required tools before finishing",
    "corrective_actions": [],
}


def agent_reply(messages: list[dict]) -> str:
    payload_text = messages[-1].get("content", "")
    if "失败经验总结器" in messages[0].get("content", ""):
        return json.dumps(REFLECTION)
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        # Free-text prompts, e.g. the final report.
        return "本次检查共发现 0 个问题。\n\n（压测用模拟回答）"
    allowed = payload.get("allowed_actions") or []
    for item in allowed:
        if item.get("action") == "call_tool":
            return json.dumps(
                {"action": "call_tool", "tool": item["tool"], "args": {}, "reason_summary": "loadtest"}
            )
    return json.dumps({"action": "finish", "tool": "", "args": {}, "reason_summary": "loadtest"})


@app.post("/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    state["calls"] += 1
    state["active"] += 1
    state["peak"] = max(state["peak"], state["active"])
    try:
        await asyncio.sleep(LATENCY_SECONDS)
        content = agent_reply(body.get("messages") or [])
    finally:
        state["active"] -= 1
    return {
        "id": f"fake-{state['calls']}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "fake"),
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.get("/stats")
def stats():
    return state


@app.post("/stats/reset")
def reset_stats():
    state.update(calls=0, active=0, peak=0)
    return state


def main() -> None:
    global LATENCY_SECONDS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--latency", type=float, default=2.0, help="seconds per LLM call")
    args = parser.parse_args()
    LATENCY_SECONDS = args.latency
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
