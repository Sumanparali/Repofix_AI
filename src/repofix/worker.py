from __future__ import annotations

import os


def main() -> None:
    try:
        from redis import Redis
        from rq import Queue, Worker
    except ImportError as exc:
        raise SystemExit('Install worker dependencies with: pip install -e ".[worker]"') from exc
    connection = Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
    worker = Worker([Queue("repofix", connection=connection)], connection=connection)
    worker.work(with_scheduler=True)

