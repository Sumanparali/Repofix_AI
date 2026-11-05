from pathlib import Path

from repofix.detector import detect_project


def test_detects_python_pytest_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths=["tests"]')
    (tmp_path / "tests").mkdir()
    profile = detect_project(tmp_path)
    assert profile.language == "python"
    assert profile.framework == "pytest"
    assert profile.test_command == ("python", "-m", "pytest", "-q")


def test_detects_maven_project(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text("<project />")
    profile = detect_project(tmp_path)
    assert profile.language == "java"
    assert profile.framework == "maven"

