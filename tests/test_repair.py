import subprocess
from pathlib import Path

from repofix.detector import detect_project
from repofix.repair import repair_repository
from repofix.retriever import retrieve_relevant_files


def test_repair_retries_after_failed_test(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths=["tests"]')
    (tmp_path / "value.py").write_text("VALUE = 0\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_value.py").write_text("from value import VALUE\n\ndef test_value(): assert VALUE == 2\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    patches = iter(
        [
            "--- a/value.py\n+++ b/value.py\n@@ -1 +1 @@\n-VALUE = 0\n+VALUE = 1\n",
            "--- a/value.py\n+++ b/value.py\n@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2\n",
        ]
    )
    feedback_seen: list[str | None] = []

    def fake_generator(issue, profile, context, model, feedback):
        feedback_seen.append(feedback)
        return next(patches)

    profile = detect_project(tmp_path)
    matches = retrieve_relevant_files(tmp_path, "VALUE should equal 2")
    history = repair_repository(
        tmp_path,
        "VALUE should equal 2",
        profile,
        matches,
        "fake",
        attempts=3,
        runner="local",
        generator=fake_generator,
    )

    assert len(history) == 2
    assert not history[0].passed
    assert history[1].passed
    assert feedback_seen[0] is None
    assert "Exit code: 1" in feedback_seen[1]
