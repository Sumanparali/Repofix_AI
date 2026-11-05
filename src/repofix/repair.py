from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .llm import generate_patch
from .models import CodeMatch, CommandResult, ProjectProfile
from .patching import apply_patch
from .retriever import build_context, retrieve_relevant_files
from .runner import run_tests as execute_tests


@dataclass(frozen=True)
class RepairAttempt:
    number: int
    patch: str
    test_result: CommandResult | None

    @property
    def passed(self) -> bool:
        return self.test_result is None or self.test_result.passed


PatchGenerator = Callable[[str, ProjectProfile, str, str, str | None], str]


def repair_repository(
    root: Path,
    issue: str,
    profile: ProjectProfile,
    matches: list[CodeMatch],
    model: str,
    *,
    attempts: int = 3,
    run_tests: bool = True,
    timeout: int = 300,
    runner: str = "docker",
    image: str | None = None,
    generator: PatchGenerator = generate_patch,
) -> list[RepairAttempt]:
    """Generate, apply, and test patches, feeding bounded failures into later attempts."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    context = build_context(root, matches)
    feedback: str | None = None
    history: list[RepairAttempt] = []

    for number in range(1, attempts + 1):
        patch = generator(issue, profile, context, model, feedback)
        apply_patch(root, patch)
        result = None
        if run_tests and profile.test_command:
            result = execute_tests(
                profile.test_command,
                root,
                timeout,
                runner=runner,
                language=profile.language,
                image=image,
            )
        attempt = RepairAttempt(number, patch, result)
        history.append(attempt)
        if attempt.passed:
            break
        feedback = _failure_feedback(result)
        matches = retrieve_relevant_files(root, issue)
        context = build_context(root, matches)
    return history


def _failure_feedback(result: CommandResult | None, limit: int = 12_000) -> str:
    if result is None:
        return "No test command was available."
    combined = f"Command: {' '.join(result.command)}\nExit code: {result.returncode}\n"
    combined += f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    return combined[-limit:]
