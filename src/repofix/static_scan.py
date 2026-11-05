from __future__ import annotations

import re
from pathlib import Path

from .models import ProjectProfile
from .retriever import IGNORED_DIRS, SOURCE_SUFFIXES


RULES = (
    ("high", "Possible hard-coded secret", re.compile(
        r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"
    ), "Move credentials to environment variables or a secret manager."),
    ("high", "Dynamic code execution", re.compile(r"\b(eval|exec)\s*\("),
     "Avoid evaluating dynamic input; use explicit parsing or dispatch."),
    ("medium", "Bare exception handler", re.compile(r"^\s*except\s*:"),
     "Catch a specific exception and preserve useful error context."),
    ("low", "Debug logging left in source", re.compile(r"\b(console\.log|debugger)\b"),
     "Remove temporary debug output or use the project logger."),
    ("low", "Unresolved maintenance marker", re.compile(r"\b(TODO|FIXME|HACK)\b", re.I),
     "Resolve or track this maintenance item before release."),
)


def scan_repository(root: Path, profile: ProjectProfile) -> list[dict]:
    findings: list[dict] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        relative = path.relative_to(root).as_posix()
        lines = text.splitlines()
        if len(lines) > 1_200:
            findings.append(_finding(
                "medium", "Oversized source file", relative, 1,
                f"This file has {len(lines)} lines; consider separating responsibilities.",
            ))
        for number, line in enumerate(lines, 1):
            for severity, title, pattern, recommendation in RULES:
                if pattern.search(line):
                    findings.append(_finding(
                        severity, title, relative, number, recommendation
                    ))
                    if len(findings) >= 200:
                        return findings
    if not _has_tests(root, profile):
        findings.append(_finding(
            "medium", "No automated tests detected", "(repository)", 0,
            "Add regression tests for critical behavior before changing production code.",
        ))
    return findings


def _has_tests(root: Path, profile: ProjectProfile) -> bool:
    if profile.test_command:
        return True
    return any((root / name).exists() for name in ("tests", "test", "spec", "__tests__"))


def _finding(severity: str, title: str, path: str, line: int, detail: str) -> dict:
    return {
        "severity": severity,
        "title": title,
        "path": path,
        "line": line,
        "detail": detail,
    }
