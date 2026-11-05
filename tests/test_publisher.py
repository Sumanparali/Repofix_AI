import subprocess
from pathlib import Path

import pytest

from repofix.github import GitHubError
from repofix.publisher import _validate_branch, changed_files


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_changed_files_includes_modified_and_untracked(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "tracked.py").write_text("old\n")
    _git(tmp_path, "add", "tracked.py")
    _git(tmp_path, "commit", "-qm", "initial")
    (tmp_path / "tracked.py").write_text("new\n")
    (tmp_path / "new.py").write_text("created\n")

    changes = changed_files(tmp_path)

    assert (" M", "tracked.py") in changes
    assert ("??", "new.py") in changes


def test_branch_must_use_repofix_namespace() -> None:
    _validate_branch("repofix/issue-42")
    with pytest.raises(GitHubError):
        _validate_branch("main")
    with pytest.raises(GitHubError):
        _validate_branch("repofix/../main")

