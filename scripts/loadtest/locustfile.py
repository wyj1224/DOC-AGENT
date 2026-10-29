"""Load test for agent task submission.

Each simulated user uploads one Word document, then repeatedly submits a
consistency check and waits for it to finish, like a person using the UI.

    LOADTEST_DOCX=path/to/doc.docx LOADTEST_MODE=queue \
        locust -f scripts/loadtest/locustfile.py --host http://127.0.0.1:8765 --headless -u 20 -r 5 -t 2m

LOADTEST_MODE=queue submits to POST /agent/tasks and polls for the result;
LOADTEST_MODE=sync calls the blocking POST /agent/check for comparison.
Besides the per-request stats, Locust reports a synthetic "TASK end-to-end"
entry: time from submission until the task reached a final status.
"""

import os
import time
from pathlib import Path

from locust import HttpUser, between, events, task

DOCX = Path(os.environ["LOADTEST_DOCX"])
MODE = os.getenv("LOADTEST_MODE", "queue")
MESSAGE = "检查正文引用和标准依据的一致性"
POLL_SECONDS = 0.5
TASK_TIMEOUT_SECONDS = 600
UNFINISHED = {"queued", "running"}

if MODE not in ("queue", "sync"):
    raise SystemExit(f"LOADTEST_MODE must be queue or sync, got {MODE!r}")


class DocumentUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        with DOCX.open("rb") as handle:
            response = self.client.post(
                "/word/upload",
                files={"file": (DOCX.name, handle, "application/octet-stream")},
                name="/word/upload",
            )
        response.raise_for_status()
        self.document_id = response.json()["document_id"]
        self.session_id = None

    def form(self) -> dict:
        data = {"document_id": str(self.document_id), "message": MESSAGE}
        if self.session_id:
            data["session_id"] = str(self.session_id)
        return data

    @task
    def run_check(self):
        if MODE == "sync":
            self.run_sync()
        else:
            self.run_queued()

    def run_sync(self):
        started = time.perf_counter()
        with self.client.post("/agent/check", data=self.form(), catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")
                return
            body = response.json()
            self.session_id = body["session_id"]
        report_task(body["status"], started)

    def run_queued(self):
        started = time.perf_counter()
        with self.client.post("/agent/tasks", data=self.form(), catch_response=True) as response:
            if response.status_code != 202:
                response.failure(f"HTTP {response.status_code}")
                return
            body = response.json()
        self.session_id = body["session_id"]
        task_id = body["task_id"]
        while True:
            time.sleep(POLL_SECONDS)
            status = self.client.get(f"/agent/tasks/{task_id}", name="/agent/tasks/[id]").json()["status"]
            if status not in UNFINISHED:
                report_task(status, started)
                return
            if time.perf_counter() - started > TASK_TIMEOUT_SECONDS:
                report_task("timeout", started)
                return


def report_task(status: str, started: float) -> None:
    events.request.fire(
        request_type="TASK",
        name="end-to-end",
        response_time=(time.perf_counter() - started) * 1000,
        response_length=0,
        exception=None if status == "success" else RuntimeError(f"task ended as {status}"),
        context={},
    )
