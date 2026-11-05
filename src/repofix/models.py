from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ProjectProfile:
    language: str
    framework: str | None
    test_command: tuple[str, ...] | None
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class CodeMatch:
    path: Path
    score: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.returncode == 0 and not self.timed_out


@dataclass
class RepairReport:
    repository: Path
    profile: ProjectProfile
    issue: str
    matches: list[CodeMatch] = field(default_factory=list)
    patch: str | None = None
    validation: CommandResult | None = None

