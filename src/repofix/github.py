from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse


class GitHubError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitHubIssue:
    owner: str
    repository: str
    number: int
    title: str
    body: str
    state: str
    labels: tuple[str, ...]
    comments: tuple[str, ...]
    html_url: str

    def as_repair_description(self) -> str:
        labels = ", ".join(self.labels) if self.labels else "none"
        sections = [
            f"GitHub issue: {self.html_url}",
            f"Title: {self.title}",
            f"State: {self.state}",
            f"Labels: {labels}",
            "Description:\n" + (self.body.strip() or "(no description provided)"),
        ]
        if self.comments:
            rendered = "\n\n".join(
                f"Comment {number}:\n{text.strip()}"
                for number, text in enumerate(self.comments, start=1)
            )
            sections.append("Discussion:\n" + rendered)
        return "\n\n".join(sections)


ISSUE_URL = re.compile(
    r"^https://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)/?$"
)
REPOSITORY_SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def parse_issue_url(url: str) -> tuple[str, str, int]:
    match = ISSUE_URL.fullmatch(url.strip())
    if not match:
        raise GitHubError("Issue URL must look like https://github.com/owner/repository/issues/123")
    owner, repository, number = match.groups()
    return owner, repository, int(number)


def repository_slug(source: str, explicit: str | None = None) -> tuple[str, str]:
    if explicit:
        if not REPOSITORY_SLUG.fullmatch(explicit):
            raise GitHubError("--github-repo must use the owner/repository format.")
        owner, repository = explicit.split("/", 1)
        return owner, repository
    parsed = urlparse(source)
    if parsed.scheme == "https" and parsed.hostname in {"github.com", "www.github.com"}:
        parts = [part for part in parsed.path.removesuffix(".git").split("/") if part]
        if len(parts) == 2:
            return parts[0], parts[1]
    raise GitHubError("Cannot infer GitHub repository; provide --github-repo owner/repository.")


def fetch_issue(
    owner: str,
    repository: str,
    number: int,
    *,
    include_comments: bool = True,
    token: str | None = None,
) -> GitHubIssue:
    if number < 1:
        raise GitHubError("Issue number must be positive.")
    base = f"https://api.github.com/repos/{owner}/{repository}/issues/{number}"
    data = _request_json(base, token=token)
    if "pull_request" in data:
        raise GitHubError(f"GitHub #{number} is a pull request, not an issue.")
    comments: tuple[str, ...] = ()
    if include_comments and data.get("comments", 0):
        comment_data = _request_json(base + "/comments?per_page=100", token=token)
        comments = tuple(item.get("body") or "" for item in comment_data[:100])
    return GitHubIssue(
        owner=owner,
        repository=repository,
        number=number,
        title=data.get("title") or "",
        body=data.get("body") or "",
        state=data.get("state") or "unknown",
        labels=tuple(label.get("name", "") for label in data.get("labels", []) if label.get("name")),
        comments=comments,
        html_url=data.get("html_url") or f"https://github.com/{owner}/{repository}/issues/{number}",
    )


def load_issue(
    *,
    issue_url: str | None = None,
    issue_number: int | None = None,
    repository_source: str,
    github_repository: str | None = None,
    include_comments: bool = True,
) -> GitHubIssue:
    if issue_url:
        owner, repository, number = parse_issue_url(issue_url)
    elif issue_number is not None:
        owner, repository = repository_slug(repository_source, github_repository)
        number = issue_number
    else:
        raise GitHubError("An issue URL or number is required.")
    return fetch_issue(
        owner,
        repository,
        number,
        include_comments=include_comments,
        token=os.getenv("GITHUB_TOKEN"),
    )


def _request_json(url: str, *, token: str | None) -> dict | list:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "RepoFix-AI/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            message = "GitHub issue was not found or the token lacks access."
        elif exc.code == 403:
            message = "GitHub denied the request; check authentication or API rate limits."
        else:
            message = f"GitHub API returned HTTP {exc.code}."
        raise GitHubError(message) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise GitHubError(f"Could not retrieve the GitHub issue: {exc}") from exc

