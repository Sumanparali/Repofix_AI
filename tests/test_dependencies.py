from pathlib import Path

from repofix.dependencies import dependency_plan
from repofix.models import ProjectProfile


def test_requirements_produce_stable_cached_image(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("requests==2.32.3\n")
    profile = ProjectProfile("python", "pytest", ("python", "-m", "pytest"))
    first = dependency_plan(tmp_path, profile)
    second = dependency_plan(tmp_path, profile)
    assert first is not None and second is not None
    assert first.image == second.image
    assert first.image.startswith("repofix-python-deps:")


def test_non_python_dependency_plan_is_not_guessed(tmp_path: Path) -> None:
    assert dependency_plan(tmp_path, ProjectProfile("java", "maven", ("mvn", "test"))) is None

