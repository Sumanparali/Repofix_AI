from __future__ import annotations

from pathlib import Path

from .detector import detect_project
from .llm import generate_patch
from .patching import PatchError, apply_patch
from .repair import repair_repository
from .repository import acquire_repository
from .retriever import build_context, retrieve_relevant_files
from .store import JobStore
from .static_scan import scan_repository


def analyze_job(
    database: str,
    identifier: int,
    repository: str,
    issue: str,
    workspace: str,
    mode: str = "analyze",
    model: str = "gpt-6.1-terra",
    runner: str = "docker",
    attempts: int = 3,
) -> dict:
    """RQ task entry point. Arguments are deliberately JSON-serializable primitives."""
    store = JobStore(database)
    store.update(identifier, "running", {"mode": mode})
    try:
        if mode not in {"analyze", "generate", "repair"}:
            raise ValueError(f"Unsupported workflow mode: {mode}")
        root = acquire_repository(repository, Path(workspace))
        profile = detect_project(root)
        matches = retrieve_relevant_files(root, issue)
        result = {
            "mode": mode,
            "language": profile.language,
            "framework": profile.framework,
            "test_command": list(profile.test_command or ()),
            "relevant_files": [
                {"path": match.path.as_posix(), "score": match.score} for match in matches
            ],
            "workspace": str(root),
        }
        if mode == "analyze":
            findings = scan_repository(root, profile)
            result["static_findings"] = findings
            if not result["relevant_files"]:
                paths = list(dict.fromkeys(
                    item["path"] for item in findings if item["path"] != "(repository)"
                ))[:8]
                result["relevant_files"] = [
                    {"path": path, "score": max(0.2, 1 - index * 0.1)}
                    for index, path in enumerate(paths)
                ]
        if mode == "generate":
            context = build_context(root, matches)
            feedback = None
            for attempt in range(2):
                patch = generate_patch(
                    issue, profile, context, model, failure_feedback=feedback
                )
                try:
                    apply_patch(root, patch, check_only=True)
                    break
                except PatchError as exc:
                    if attempt == 1:
                        raise
                    feedback = (
                        "The previous unified diff failed validation with this error: "
                        f"{exc}\nReturn a complete corrected unified diff only."
                    )
            result.update({"patch": patch, "patch_valid": True})
        elif mode == "repair":
            if profile.test_command is None:
                raise ValueError("Repair verification requires a detected test command.")
            history = repair_repository(
                root,
                issue,
                profile,
                matches,
                model,
                attempts=attempts,
                run_tests=True,
                runner=runner,
            )
            final = history[-1]
            result.update(
                {
                    "patch": final.patch,
                    "patch_valid": True,
                    "passed": final.passed,
                    "attempts": len(history),
                    "test": _command_result(final.test_result),
                }
            )
            if not final.passed:
                result["report"] = _build_report(issue, result)
                store.update(identifier, "failed", result)
                return result
        result["report"] = _build_report(issue, result)
        store.update(identifier, "completed", result)
        return result
    except Exception as exc:
        store.update(identifier, "failed", {"error": str(exc), "mode": mode})
        raise


def _command_result(result) -> dict | None:
    if result is None:
        return None
    return {
        "command": list(result.command),
        "returncode": result.returncode,
        "stdout": result.stdout[-50_000:],
        "stderr": result.stderr[-50_000:],
        "timed_out": result.timed_out,
        "passed": result.passed,
    }


def _build_report(issue: str, result: dict) -> dict:
    patch = str(result.get("patch", ""))
    changed_files: list[str] = []
    additions = deletions = 0
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            changed_files.append(line[6:])
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    relevant = [item["path"] for item in result.get("relevant_files", [])]
    mode = result.get("mode", "analyze")
    if patch:
        outcome = (
            f"AI produced a valid patch affecting {len(changed_files)} file(s), "
            f"with {additions} addition(s) and {deletions} deletion(s)."
        )
    else:
        count = len(result.get("static_findings", []))
        outcome = (
            f"Local static analysis completed with {count} finding(s). "
            "No external AI service or repository code upload was used."
        )
    recommendations = [
        "Review high-severity findings first, then address medium and low-severity items.",
        "Run the detected test command after making changes.",
    ]
    if mode == "generate":
        recommendations.insert(0, "Review and approve the generated patch before applying it.")
    elif mode == "repair":
        recommendations.insert(0, "Inspect the patch and attached test evidence before publication.")
    return {
        "title": "RepoFix analysis report",
        "issue": issue,
        "outcome": outcome,
        "language": result.get("language") or "Unknown",
        "framework": result.get("framework") or "Not detected",
        "relevant_files": relevant,
        "changed_files": changed_files,
        "additions": additions,
        "deletions": deletions,
        "recommendations": recommendations,
        "findings": result.get("static_findings", []),
        "validation": (
            "Tests passed" if result.get("passed") is True
            else "Patch syntax validated" if result.get("patch_valid")
            else "Local static scan completed; no patch was generated"
        ),
    }

