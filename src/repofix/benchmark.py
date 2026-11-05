from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

from .detector import detect_project
from .repository import acquire_repository
from .retriever import retrieve_relevant_files


def run_dataset(dataset: Path, output: Path, workspace: Path) -> None:
    cases = json.loads(dataset.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError("Benchmark dataset must be a JSON array.")
    rows: list[dict] = []
    for case in cases:
        started = time.monotonic()
        status, error, language = "analyzed", "", ""
        matches: list = []
        try:
            root = acquire_repository(case["repository"], workspace)
            profile = detect_project(root)
            language = profile.language
            matches = retrieve_relevant_files(root, case["issue"], limit=case.get("top_k", 8))
        except Exception as exc:
            status, error = "failed", str(exc)
        expected = case.get("expected_file")
        paths = [match.path.as_posix() for match in matches]
        rows.append({"id": case.get("id", ""), "status": status, "language": language, "top_k_hit": bool(expected and expected in paths), "retrieved_files": json.dumps(paths), "seconds": round(time.monotonic() - started, 4), "error": error})
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "status", "language", "top_k_hit", "retrieved_files", "seconds", "error"]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run RepoFix localization benchmarks")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, default=Path("benchmark-results.csv"))
    parser.add_argument("--workspace", type=Path, default=Path(".repofix-work/benchmarks"))
    args = parser.parse_args(argv)
    run_dataset(args.dataset, args.output, args.workspace.resolve())

