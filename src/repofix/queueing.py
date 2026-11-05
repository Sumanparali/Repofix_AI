from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4


class QueueUnavailable(RuntimeError):
    pass


_local_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="repofix-local")


def _queue_mode() -> str:
    mode = os.getenv("REPOFIX_QUEUE_MODE", "auto").strip().lower()
    if mode not in {"auto", "redis", "local"}:
        raise QueueUnavailable("REPOFIX_QUEUE_MODE must be one of: auto, redis, local")
    return mode


def _database_value(database: str | Path) -> str:
    raw = str(database)
    return raw if "://" in raw else str(Path(raw).resolve())


def _enqueue_local(
    database: str | Path,
    identifier: int,
    repository: str,
    issue: str,
    workspace: Path,
    mode: str,
    model: str,
    runner: str,
    attempts: int,
) -> str:
    from .tasks import analyze_job

    queue_id = f"local-{uuid4()}"
    _local_executor.submit(
        analyze_job,
        _database_value(database),
        identifier,
        repository,
        issue,
        str(workspace.resolve()),
        mode,
        model,
        runner,
        attempts,
    )
    return queue_id


def enqueue_analysis(
    database: str | Path,
    identifier: int,
    repository: str,
    issue: str,
    workspace: Path,
    mode: str = "analyze",
    model: str = "gpt-6.1-terra",
    runner: str = "docker",
    attempts: int = 3,
) -> str:
    queue_mode = _queue_mode()
    if queue_mode == "local":
        return _enqueue_local(
            database, identifier, repository, issue, workspace, mode, model, runner, attempts
        )
    try:
        from redis import Redis
        from rq import Queue
    except ImportError as exc:
        if queue_mode == "auto":
            return _enqueue_local(
                database, identifier, repository, issue, workspace, mode, model, runner, attempts
            )
        raise QueueUnavailable('Install worker dependencies with: pip install -e ".[worker]"') from exc
    connection = Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
    try:
        connection.ping()
        queue = Queue("repofix", connection=connection, default_timeout=1800)
        queued = queue.enqueue(
            "repofix.tasks.analyze_job",
            _database_value(database),
            identifier,
            repository,
            issue,
            str(workspace.resolve()),
            mode,
            model,
            runner,
            attempts,
            job_timeout=1800,
            result_ttl=86400,
            failure_ttl=604800,
        )
    except Exception as exc:
        if queue_mode == "auto":
            return _enqueue_local(
                database, identifier, repository, issue, workspace, mode, model, runner, attempts
            )
        raise QueueUnavailable(f"Redis queue is unavailable: {exc}") from exc
    return queued.id


def cancel_analysis(queue_id: str) -> bool:
    """Cancel a queued Redis analysis before a worker starts it."""
    if _queue_mode() != "redis" or not queue_id:
        return False
    try:
        from redis import Redis
        from rq.job import Job

        connection = Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
        queued = Job.fetch(queue_id, connection=connection)
        queued.cancel()
        return True
    except Exception:
        return False


def queue_health() -> dict:
    try:
        mode = _queue_mode()
    except QueueUnavailable as exc:
        return {"available": False, "queued": None, "backend": "invalid", "redis": str(exc)}
    if mode == "local":
        return {"available": True, "queued": None, "backend": "local", "redis": "not required"}
    try:
        from redis import Redis
        from rq import Queue
        connection = Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
        connection.ping()
        queue = Queue("repofix", connection=connection)
        return {"available": True, "queued": len(queue), "backend": "redis", "redis": "connected"}
    except Exception as exc:
        if mode == "auto":
            return {"available": True, "queued": None, "backend": "local", "redis": str(exc)}
        return {"available": False, "queued": None, "redis": str(exc)}

