"""Run queued AgentTasks.

    python -m app.cli.worker --concurrency 4

Each slot is a thread that claims one task at a time from PostgreSQL. Run more
processes (or containers) to scale out; SKIP LOCKED keeps them from colliding.
"""

import argparse
import logging
import os
import signal
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.agent.task_queue import claim_next_task, heartbeat, reap_stale_tasks
from app.agent.workflow import run_agent_task


logger = logging.getLogger("agent-worker")


class Worker:
    def __init__(
        self,
        *,
        concurrency: int,
        poll_interval: float,
        heartbeat_interval: float,
        stale_after: float,
        worker_id: str | None = None,
    ) -> None:
        if heartbeat_interval * 2 > stale_after:
            raise ValueError("stale_after must be at least twice heartbeat_interval")
        self.concurrency = concurrency
        self.poll_interval = poll_interval
        self.heartbeat_interval = heartbeat_interval
        self.stale_after = stale_after
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.stopping = threading.Event()

    def run(self) -> None:
        logger.info("worker %s started with %d slots", self.worker_id, self.concurrency)
        with ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix="slot") as pool:
            for slot in range(self.concurrency):
                pool.submit(self.slot_loop, slot)
            while not self.stopping.wait(self.stale_after / 2):
                for task_id in reap_stale_tasks(self.stale_after):
                    logger.warning("task %s marked stale: its worker stopped heartbeating", task_id)
        logger.info("worker %s stopped", self.worker_id)

    def stop(self) -> None:
        """Stop claiming new tasks; tasks already running are allowed to finish."""
        self.stopping.set()

    def slot_loop(self, slot: int) -> None:
        while not self.stopping.is_set():
            try:
                task_id = claim_next_task(self.worker_id)
            except Exception:
                logger.exception("slot %d failed to claim a task", slot)
                self.stopping.wait(self.poll_interval)
                continue
            if task_id is None:
                self.stopping.wait(self.poll_interval)
                continue
            self.execute(task_id)

    def execute(self, task_id: int) -> None:
        done = threading.Event()
        beat = threading.Thread(
            target=self.heartbeat_loop, args=(task_id, done), daemon=True
        )
        beat.start()
        started = time.monotonic()
        logger.info("task %s started", task_id)
        try:
            result = run_agent_task(task_id)
            logger.info(
                "task %s finished with %s in %.1fs",
                task_id,
                result.get("status"),
                time.monotonic() - started,
            )
        except Exception:
            # run_agent_task already stored the error on the task row.
            logger.exception("task %s crashed", task_id)
        finally:
            done.set()
            beat.join()

    def heartbeat_loop(self, task_id: int, done: threading.Event) -> None:
        while not done.wait(self.heartbeat_interval):
            try:
                if not heartbeat(task_id, self.worker_id):
                    logger.warning("task %s is no longer owned by this worker", task_id)
                    return
            except Exception:
                logger.exception("heartbeat for task %s failed", task_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run queued agent tasks.")
    parser.add_argument(
        "--concurrency", type=int, default=int(os.getenv("WORKER_CONCURRENCY", "2"))
    )
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--heartbeat-interval", type=float, default=10.0)
    parser.add_argument("--stale-after", type=float, default=60.0)
    args = parser.parse_args()
    if args.concurrency < 1:
        parser.error("--concurrency must be at least 1")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s [%(threadName)s] %(message)s",
    )
    worker = Worker(
        concurrency=args.concurrency,
        poll_interval=args.poll_interval,
        heartbeat_interval=args.heartbeat_interval,
        stale_after=args.stale_after,
    )
    signal.signal(signal.SIGTERM, lambda *_: worker.stop())
    signal.signal(signal.SIGINT, lambda *_: worker.stop())
    worker.run()


if __name__ == "__main__":
    main()
