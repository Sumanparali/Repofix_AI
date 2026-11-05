from pathlib import Path

from repofix.models import CommandResult
from repofix.repair import RepairAttempt
from repofix.store import JobStore
from repofix.tasks import analyze_job


def test_background_analysis_updates_job(tmp_path: Path) -> None:
    repository = tmp_path / "source"
    repository.mkdir()
    (repository / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths=["tests"]')
    (repository / "email.py").write_text("def validate_email(value): return value")
    database = tmp_path / "jobs.db"
    store = JobStore(database)
    job = store.create(str(repository), "email validation fails")

    result = analyze_job(str(database), job.id, str(repository), "email validation fails", str(tmp_path / "work"))

    updated = store.get(job.id)
    assert updated is not None
    assert updated.status == "completed"
    assert result["language"] == "python"
    assert result["relevant_files"][0]["path"] == "email.py"


def test_background_generation_persists_validated_patch(monkeypatch, tmp_path: Path) -> None:
    repository = tmp_path / "source"
    repository.mkdir()
    (repository / "app.py").write_text("VALUE = 1\n")
    database = tmp_path / "jobs.db"
    store = JobStore(database)
    job = store.create(str(repository), "change VALUE to 2")
    patch = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2\n"
    monkeypatch.setattr("repofix.tasks.generate_patch", lambda *args: patch)

    result = analyze_job(
        str(database),
        job.id,
        str(repository),
        "change VALUE to 2",
        str(tmp_path / "work"),
        "generate",
    )

    updated = store.get(job.id)
    assert updated is not None
    assert updated.status == "completed"
    assert result["patch"] == patch
    assert result["patch_valid"] is True
    assert result["report"]["validation"] == "Patch syntax validated"
    assert result["report"]["changed_files"] == ["app.py"]
    assert (repository / "app.py").read_text() == "VALUE = 1\n"


def test_background_repair_persists_test_evidence(monkeypatch, tmp_path: Path) -> None:
    repository = tmp_path / "source"
    repository.mkdir()
    (repository / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths=["tests"]')
    (repository / "tests").mkdir()
    (repository / "app.py").write_text("VALUE = 1\n")
    database = tmp_path / "jobs.db"
    store = JobStore(database)
    job = store.create(str(repository), "change VALUE")
    patch = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2\n"
    command = CommandResult(("python", "-m", "pytest", "-q"), 0, "1 passed\n", "")
    monkeypatch.setattr(
        "repofix.tasks.repair_repository",
        lambda *args, **kwargs: [RepairAttempt(1, patch, command)],
    )

    result = analyze_job(
        str(database),
        job.id,
        str(repository),
        "change VALUE",
        str(tmp_path / "work"),
        "repair",
    )

    assert store.get(job.id).status == "completed"
    assert result["passed"] is True
    assert result["test"]["stdout"] == "1 passed\n"

