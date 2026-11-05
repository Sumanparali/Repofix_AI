from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

from .models import CommandResult

DOCKER_IMAGES = {
    "python": "repofix-python-runner:0.1",
    "java": "repofix-java-runner:0.1",
    "javascript/typescript": "repofix-node-runner:0.1",
}


def run_command(command: tuple[str, ...], cwd: Path, timeout: int = 300) -> CommandResult:
    """Run an adapter-selected command without invoking a shell."""
    try:
        process = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            errors="replace",
        )
        return CommandResult(command, process.returncode, process.stdout, process.stderr)
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command,
            124,
            _to_text(exc.stdout),
            _to_text(exc.stderr),
            timed_out=True,
        )
    except OSError as exc:
        return CommandResult(command, 127, "", str(exc))


def run_tests(
    command: tuple[str, ...],
    cwd: Path,
    timeout: int = 300,
    *,
    runner: str = "docker",
    language: str = "python",
    image: str | None = None,
) -> CommandResult:
    if runner == "local":
        return run_command(command, cwd, timeout)
    if runner != "docker":
        return CommandResult(command, 2, "", f"Unknown runner: {runner}")
    return run_in_docker(command, cwd, timeout, language=language, image=image)


def docker_command(
    command: tuple[str, ...],
    cwd: Path,
    *,
    language: str,
    image: str | None = None,
) -> tuple[str, ...]:
    image = image or DOCKER_IMAGES.get(language)
    if image is None:
        raise ValueError(f"No Docker runner image is configured for language: {language}")
    return (
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--memory",
        "1g",
        "--cpus",
        "1.0",
        "--pids-limit",
        "256",
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--user",
        "65532:65532",
        "--mount",
        f"type=bind,source={cwd.resolve()},target=/workspace",
        "--workdir",
        "/workspace",
        image,
        *command,
    )


def run_in_docker(
    command: tuple[str, ...],
    cwd: Path,
    timeout: int = 300,
    *,
    language: str = "python",
    image: str | None = None,
) -> CommandResult:
    if shutil.which("docker") is None:
        return CommandResult(command, 127, "", "Docker was not found. Install Docker or use --runner local explicitly.")
    try:
        docker = docker_command(command, cwd, language=language, image=image)
    except ValueError as exc:
        return CommandResult(command, 2, "", str(exc))
    result = run_command(docker, cwd, timeout)
    # Report the project command to callers while retaining Docker diagnostics.
    return CommandResult(command, result.returncode, result.stdout, result.stderr, result.timed_out)


def _to_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value
