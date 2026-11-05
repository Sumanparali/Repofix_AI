from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .github import GitHubError, repository_slug


@dataclass(frozen=True)
class PullRequestResult:
    number: int
    url: str
    branch: str


def changed_files(root: Path) -> tuple[tuple[str, str], ...]:
    """Return (status, path) entries, including untracked files."""
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=root,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode:
        raise GitHubError("Pull Request creation requires a Git repository.")
    entries = result.stdout.split("\0")
    changes: list[tuple[str, str]] = []
    index = 0
    while index < len(entries) and entries[index]:
        entry = entries[index]
        status = entry[:2]
        path = entry[3:]
        if "R" in status or "C" in status:
            index += 1
            if index >= len(entries):
                raise GitHubError("Could not parse renamed Git files.")
            path = entries[index]
        _validate_relative_path(path)
        changes.append((status, path))
        index += 1
    return tuple(changes)


def create_pull_request(
    root: Path,
    repository_source: str,
    *,
    title: str,
    body: str,
    github_repository: str | None = None,
    branch: str | None = None,
    token: str | None = None,
) -> PullRequestResult:
    token = token or os.getenv("GITHUB_TOKEN")
    if not token:
        raise GitHubError("GITHUB_TOKEN is required to create a Pull Request.")
    owner, repository = repository_slug(repository_source, github_repository)
    changes = changed_files(root)
    if not changes:
        raise GitHubError("There are no changed files to publish.")

    repo_api = f"https://api.github.com/repos/{owner}/{repository}"
    metadata = _api("GET", repo_api, token=token)
    default_branch = metadata["default_branch"]
    ref = _api("GET", f"{repo_api}/git/ref/heads/{_quote(default_branch)}", token=token)
    base_sha = ref["object"]["sha"]
    commit = _api("GET", f"{repo_api}/git/commits/{base_sha}", token=token)
    base_tree = commit["tree"]["sha"]

    tree_entries: list[dict] = []
    for status, relative in changes:
        if "D" in status:
            tree_entries.append({"path": _git_path(relative), "mode": "100644", "type": "blob", "sha": None})
            continue
        path = root / Path(relative)
        if path.is_symlink():
            raise GitHubError(f"Refusing to publish symbolic link: {relative}")
        content = base64.b64encode(path.read_bytes()).decode("ascii")
        blob = _api(
            "POST",
            f"{repo_api}/git/blobs",
            token=token,
            payload={"content": content, "encoding": "base64"},
        )
        executable = bool(path.stat().st_mode & 0o111)
        tree_entries.append(
            {"path": _git_path(relative), "mode": "100755" if executable else "100644", "type": "blob", "sha": blob["sha"]}
        )

    tree = _api(
        "POST",
        f"{repo_api}/git/trees",
        token=token,
        payload={"base_tree": base_tree, "tree": tree_entries},
    )
    new_commit = _api(
        "POST",
        f"{repo_api}/git/commits",
        token=token,
        payload={"message": title, "tree": tree["sha"], "parents": [base_sha]},
    )
    branch = branch or f"repofix/{uuid.uuid4().hex[:10]}"
    _validate_branch(branch)
    _api(
        "POST",
        f"{repo_api}/git/refs",
        token=token,
        payload={"ref": f"refs/heads/{branch}", "sha": new_commit["sha"]},
    )
    pull = _api(
        "POST",
        f"{repo_api}/pulls",
        token=token,
        payload={"title": title, "body": body, "head": branch, "base": default_branch},
    )
    return PullRequestResult(pull["number"], pull["html_url"], branch)


def _api(method: str, url: str, *, token: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "RepoFix-AI/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise GitHubError(f"GitHub publishing failed with HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise GitHubError(f"GitHub publishing failed: {exc}") from exc


def _validate_relative_path(path: str) -> None:
    pure = PurePosixPath(path.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise GitHubError(f"Unsafe changed path: {path}")


def _git_path(path: str) -> str:
    _validate_relative_path(path)
    return PurePosixPath(path.replace("\\", "/")).as_posix()


def _validate_branch(branch: str) -> None:
    if not branch.startswith("repofix/") or any(value in branch for value in ("..", " ", "~", "^", ":", "?", "*", "[", "\\")):
        raise GitHubError("Branch must be a safe name under repofix/.")


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")

