from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath


class PatchError(RuntimeError):
    pass


def validate_patch_text(patch: str) -> None:
    if not patch.strip():
        raise PatchError("The generated patch is empty.")
    if "\x00" in patch:
        raise PatchError("Patch contains a null byte.")
    lines = patch.splitlines()
    old_headers = [line[4:] for line in lines if line.startswith("--- ")]
    new_headers = [line[4:] for line in lines if line.startswith("+++ ")]
    if not old_headers or len(old_headers) != len(new_headers) or not any(
        line.startswith("@@") for line in lines
    ):
        raise PatchError("The response is not a unified diff.")
    for header in (*old_headers, *new_headers):
        _validate_header_path(header)


def _validate_header_path(header: str) -> None:
    value = header.split("\t", 1)[0].strip()
    if value == "/dev/null":
        return
    if value.startswith('"') or "\\" in value:
        raise PatchError("Patch paths must be unquoted repository-relative paths.")
    path = PurePosixPath(value)
    if path.is_absolute() or len(path.parts) < 2 or path.parts[0] not in {"a", "b"}:
        raise PatchError("Patch contains a path outside the repository.")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise PatchError("Patch contains a path outside the repository.")


def apply_patch(root: Path, patch: str, check_only: bool = False) -> None:
    validate_patch_text(patch)
    command = ["git", "apply", "--check"] if check_only else ["git", "apply"]
    result = subprocess.run(
        command,
        cwd=root,
        input=patch,
        text=True,
        capture_output=True,
        shell=False,
    )
    if result.returncode:
        raise PatchError(result.stderr.strip() or "git apply failed")

