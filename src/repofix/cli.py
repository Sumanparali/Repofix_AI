from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .detector import detect_project
from .dependencies import prepare_dependencies
from .github import GitHubError, load_issue
from .llm import LLMError, generate_patch
from .patching import PatchError, apply_patch
from .publisher import create_pull_request
from .repair import repair_repository
from .repository import RepositoryError, acquire_repository
from .retriever import build_context, retrieve_relevant_files
from .runner import run_tests


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze a repository issue and propose a tested patch.")
    parser.add_argument("--repo", required=True, help="Local directory or public GitHub HTTPS URL")
    issue = parser.add_mutually_exclusive_group(required=True)
    issue.add_argument("--issue", help="Issue description")
    issue.add_argument("--issue-file", type=Path, help="UTF-8 file containing the issue")
    issue.add_argument("--issue-url", help="GitHub issue URL")
    issue.add_argument("--issue-number", type=int, help="GitHub issue number")
    parser.add_argument(
        "--github-repo",
        help="GitHub owner/repository, needed when using an issue number with a local directory",
    )
    parser.add_argument(
        "--no-comments",
        action="store_true",
        help="Do not include GitHub issue comments",
    )
    parser.add_argument("--generate", action="store_true", help="Generate a patch using the OpenAI API")
    parser.add_argument("--apply", action="store_true", help="Apply the generated patch (implies --generate)")
    parser.add_argument("--test", action="store_true", help="Run the detected test command")
    parser.add_argument("--model", default="gpt-6.1-terra", help="OpenAI model for patch generation")
    parser.add_argument("--limit", type=int, default=8, help="Maximum relevant files to retrieve")
    parser.add_argument("--timeout", type=int, default=300, help="Test timeout in seconds")
    parser.add_argument(
        "--runner",
        choices=("docker", "local"),
        default="docker",
        help="Test execution environment; local must be selected explicitly",
    )
    parser.add_argument("--attempts", type=int, default=3, help="Maximum AI repair attempts")
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Operate on the given local directory instead of an isolated copy",
    )
    parser.add_argument("--workspace", type=Path, default=Path(".repofix-work"))
    parser.add_argument("--output", type=Path, default=Path("repofix-output/fix.diff"))
    parser.add_argument(
        "--create-pr",
        action="store_true",
        help="Publish a passing repair branch and create a GitHub Pull Request",
    )
    parser.add_argument("--branch", help="PR branch name; must start with repofix/")
    parser.add_argument("--prepare", action="store_true", help="Build a dependency image before tests")
    parser.add_argument("--rebuild-image", action="store_true", help="Rebuild a cached dependency image")
    parser.add_argument("--dependency-timeout", type=int, default=600)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        github_issue = None
        if args.issue or args.issue_file:
            issue = args.issue or args.issue_file.read_text(encoding="utf-8")
        else:
            github_issue = load_issue(
                issue_url=args.issue_url,
                issue_number=args.issue_number,
                repository_source=args.repo,
                github_repository=args.github_repo,
                include_comments=not args.no_comments,
            )
            issue = github_issue.as_repair_description()
            print(f"Loaded GitHub issue #{github_issue.number}: {github_issue.title}")
        root = acquire_repository(args.repo, args.workspace.resolve(), isolated=not args.in_place)
        profile = detect_project(root)
        dependency_image = None
        if args.prepare:
            dependency_image, preparation = prepare_dependencies(root, profile, timeout=args.dependency_timeout, rebuild=args.rebuild_image)
            if preparation is None:
                print("No supported dependency manifest was detected.")
            elif not preparation.passed:
                print(preparation.stderr, file=sys.stderr)
                return 1
            else:
                print(f"Dependency image ready: {dependency_image}")
        matches = retrieve_relevant_files(root, issue, max(1, args.limit))

        print(f"Repository: {root}")
        print(f"Detected: {profile.language} / {profile.framework or 'unknown framework'}")
        print("Relevant files:")
        for match in matches:
            print(f"  {match.score:5.1f}  {match.path}")
        if not matches:
            print("  No source files matched the issue terms.")

        patch: str | None = None
        tests_ran_during_repair = False
        repair_passed = False
        repair_attempt_count = 0
        if args.apply:
            if args.attempts < 1:
                raise ValueError("--attempts must be at least 1")
            history = repair_repository(
                root,
                issue,
                profile,
                matches,
                args.model,
                attempts=args.attempts,
                run_tests=args.test,
                timeout=args.timeout,
                runner=args.runner,
                image=dependency_image,
            )
            tests_ran_during_repair = args.test and profile.test_command is not None
            patch = history[-1].patch
            repair_passed = history[-1].passed
            repair_attempt_count = len(history)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(patch + "\n", encoding="utf-8")
            for attempt in history:
                state = "PASSED" if attempt.passed else "FAILED"
                print(f"Repair attempt {attempt.number}: {state}")
            print(f"Applied patch in isolated workspace; saved final diff to {args.output}")
        elif args.generate:
            context = build_context(root, matches)
            patch = generate_patch(issue, profile, context, args.model)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(patch + "\n", encoding="utf-8")
            apply_patch(root, patch, check_only=True)
            print(f"Validated patch; saved to {args.output}")

        if args.test and not tests_ran_during_repair:
            if not profile.test_command:
                print("No trusted test command was detected.", file=sys.stderr)
                return 2
            result = run_tests(
                profile.test_command,
                root,
                args.timeout,
                runner=args.runner,
                language=profile.language,
                image=dependency_image,
            )
            print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="")
            print(f"Tests: {'PASSED' if result.passed else 'FAILED'}")
            if not result.passed:
                return 1
        if args.create_pr:
            if not args.apply or not args.test:
                raise GitHubError("--create-pr requires both --apply and --test.")
            if not tests_ran_during_repair or not repair_passed:
                raise GitHubError("Pull Request creation requires a passing final repair attempt.")
            issue_label = f"#{github_issue.number}" if github_issue else "reported issue"
            title = f"fix: resolve {issue_label} with RepoFix AI"
            body = (
                "## Summary\n\n"
                "Automated repair generated for the supplied issue.\n\n"
                "## Validation\n\n"
                f"- Test command: `{' '.join(profile.test_command or ())}`\n"
                "- Final status: passed\n"
                f"- Repair attempts: {repair_attempt_count}\n\n"
                "This Pull Request was generated by RepoFix AI and requires developer review."
            )
            pull = create_pull_request(
                root,
                args.repo,
                title=title,
                body=body,
                github_repository=args.github_repo,
                branch=args.branch,
            )
            print(f"Created Pull Request #{pull.number}: {pull.url}")
        return 0
    except (OSError, RepositoryError, GitHubError, LLMError, PatchError, UnicodeError, ValueError) as exc:
        print(f"RepoFix error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
