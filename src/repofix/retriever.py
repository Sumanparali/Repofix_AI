from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .models import CodeMatch

SOURCE_SUFFIXES = {".py", ".java", ".js", ".jsx", ".ts", ".tsx", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs"}
IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "build", "target", "__pycache__"}
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has",
    "have", "if", "in", "is", "it", "not", "of", "on", "or", "that", "the", "this",
    "to", "was", "when", "with", "should", "expected", "actual", "issue", "error",
}


def issue_terms(issue: str) -> list[str]:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", issue.lower())
    counts = Counter(word for word in words if word not in STOP_WORDS)
    return [word for word, _ in counts.most_common(30)]


def retrieve_relevant_files(root: Path, issue: str, limit: int = 8) -> list[CodeMatch]:
    terms = issue_terms(issue)
    matches: list[CodeMatch] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        try:
            if path.stat().st_size > 500_000:
                continue
            content = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        relative = path.relative_to(root)
        filename = relative.as_posix().lower()
        score = 0.0
        reasons: list[str] = []
        for term in terms:
            occurrences = min(content.count(term), 10)
            if occurrences:
                score += occurrences
                reasons.append(f"'{term}' in content")
            if term in filename:
                score += 5
                reasons.append(f"'{term}' in path")
        if "test" in filename:
            score *= 0.9
        if score:
            matches.append(CodeMatch(relative, score, tuple(dict.fromkeys(reasons))))
    return sorted(matches, key=lambda item: (-item.score, item.path.as_posix()))[:limit]


def build_context(root: Path, matches: list[CodeMatch], max_chars: int = 24_000) -> str:
    sections: list[str] = []
    used = 0
    for match in matches:
        text = (root / match.path).read_text(encoding="utf-8", errors="ignore")
        section = f"\n--- {match.path.as_posix()} ---\n{text}"
        remaining = max_chars - used
        if remaining <= 0:
            break
        sections.append(section[:remaining])
        used += len(section)
    return "".join(sections)

