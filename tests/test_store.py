from pathlib import Path

from repofix.store import JobStore


def test_job_lifecycle(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    created = store.create("repo", "issue")
    assert created.status == "queued"
    updated = store.update(created.id, "complete", {"passed": True})
    assert updated.result == {"passed": True}
    assert store.get(created.id) == updated
    assert store.list() == [updated]

