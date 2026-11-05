from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlparse


class RepositoryError(RuntimeError):
    pass


def validate_github_repository_url(source: str) -> str:
    """Return a normalized public GitHub clone URL or raise a user-facing error."""
    parsed = urlparse(source)
    path_parts = [part for part in parsed.path.split("/") if part]
    try:
        port = parsed.port
    except ValueError as exc:
        raise RepositoryError("GitHub repository URL contains an invalid port.") from exc
    valid = (
        parsed.scheme == "https"
        and parsed.hostname in {"github.com", "www.github.com"}
        and port in {None, 443}
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and len(path_parts) == 2
        and all(part not in {".", ".."} for part in path_parts)
    )
    if not valid:
        raise RepositoryError(
            "Repository URL must be a public HTTPS GitHub URL in the form "
            "https://github.com/owner/repository."
        )
    owner, repository = path_parts
    repository = repository.removesuffix(".git")
    if not owner or not repository:
        raise RepositoryError("GitHub repository owner and name are required.")
    return f"https://github.com/{owner}/{repository}.git"


def acquire_repository(source: str, workspace: Path, *, isolated: bool = True) -> Path:
    local = Path(source).expanduser()
    if local.exists() and local.is_dir():
        local = local.resolve()
        if not isolated:
            return local
        return _copy_local_repository(local, workspace)
    clone_url = validate_github_repository_url(source)
    if shutil.which("git") is None:
        raise RepositoryError("Git is required to clone repositories.")
    name = Path(urlparse(clone_url).path).stem or "repository"
    target = _job_path(workspace, name)
    workspace.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", "--depth", "1", clone_url, str(target)],
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode:
        raise RepositoryError(result.stderr.strip() or "Git clone failed.")
    return target.resolve()


def _copy_local_repository(source: Path, workspace: Path) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    target = _job_path(workspace, source.name or "repository")
    if (source / ".git").exists() and shutil.which("git"):
        result = subprocess.run(
            ["git", "clone", "--no-hardlinks", "--quiet", str(source), str(target)],
            capture_output=True,
            text=True,
            shell=False,
        )
        if result.returncode:
            raise RepositoryError(result.stderr.strip() or "Local Git clone failed.")
    else:
        ignored = shutil.ignore_patterns(
            ".git", ".repofix-work", ".venv", "venv", "node_modules", "__pycache__"
        )
        try:
            shutil.copytree(source, target, ignore=ignored)
        except OSError as exc:
            raise RepositoryError(f"Could not create isolated repository copy: {exc}") from exc
    return target.resolve()


def _job_path(workspace: Path, name: str) -> Path:
    safe_name = "".join(character for character in name if character.isalnum() or character in "-_")
    return workspace / f"{safe_name or 'repository'}-{uuid.uuid4().hex[:8]}"
