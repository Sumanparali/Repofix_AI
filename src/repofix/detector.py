from __future__ import annotations

import json
from pathlib import Path

from .models import ProjectProfile


def detect_project(root: Path) -> ProjectProfile:
    """Detect a project's primary language and safe, known test command."""
    evidence: list[str] = []

    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        evidence.extend(_existing(root, "pyproject.toml", "requirements.txt", "setup.py"))
        framework = "pytest" if _has_pytest(root) else None
        command = ("python", "-m", "pytest", "-q") if framework else None
        return ProjectProfile("python", framework, command, tuple(evidence))

    if (root / "pom.xml").exists():
        return ProjectProfile("java", "maven", ("mvn", "test", "-q"), ("pom.xml",))

    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        evidence.extend(_existing(root, "build.gradle", "build.gradle.kts"))
        wrapper = "gradlew.bat" if (root / "gradlew.bat").exists() else "gradle"
        return ProjectProfile("java", "gradle", (wrapper, "test"), tuple(evidence))

    if (root / "package.json").exists():
        evidence.append("package.json")
        framework = _node_test_framework(root / "package.json")
        return ProjectProfile("javascript/typescript", framework, ("npm", "test", "--", "--run"), tuple(evidence))

    if (root / "CMakeLists.txt").exists():
        return ProjectProfile("c/c++", "cmake", None, ("CMakeLists.txt",))

    extensions = {p.suffix.lower() for p in root.rglob("*") if p.is_file()}
    if ".py" in extensions:
        return ProjectProfile("python", None, None, ("*.py",))
    if extensions & {".js", ".ts", ".tsx"}:
        return ProjectProfile("javascript/typescript", None, None, ("source extensions",))
    return ProjectProfile("unknown", None, None)


def _existing(root: Path, *names: str) -> list[str]:
    return [name for name in names if (root / name).exists()]


def _has_pytest(root: Path) -> bool:
    if (root / "pytest.ini").exists() or (root / "conftest.py").exists():
        return True
    for name in ("pyproject.toml", "requirements.txt", "setup.cfg", "tox.ini"):
        path = root / name
        if path.exists() and "pytest" in path.read_text(encoding="utf-8", errors="ignore").lower():
            return True
    return (root / "tests").is_dir()


def _node_test_framework(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    contents = json.dumps(data).lower()
    for name in ("vitest", "jest", "mocha"):
        if name in contents:
            return name
    return "npm"

