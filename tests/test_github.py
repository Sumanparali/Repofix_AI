import json
from unittest.mock import patch

import pytest

from repofix.github import GitHubError, fetch_issue, parse_issue_url, repository_slug


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def test_parse_issue_url() -> None:
    assert parse_issue_url("https://github.com/acme/widget/issues/42") == ("acme", "widget", 42)


def test_rejects_non_github_issue_url() -> None:
    with pytest.raises(GitHubError):
        parse_issue_url("https://example.com/acme/widget/issues/42")


def test_repository_slug_from_clone_url() -> None:
    assert repository_slug("https://github.com/acme/widget.git") == ("acme", "widget")


def test_local_repository_needs_explicit_slug() -> None:
    with pytest.raises(GitHubError):
        repository_slug("C:/projects/widget")
    assert repository_slug("C:/projects/widget", "acme/widget") == ("acme", "widget")


def test_fetch_issue_includes_comments() -> None:
    issue = {
        "title": "Crash on empty input",
        "body": "Steps to reproduce",
        "state": "open",
        "labels": [{"name": "bug"}],
        "comments": 1,
        "html_url": "https://github.com/acme/widget/issues/7",
    }
    comments = [{"body": "Stack trace here"}]
    with patch("urllib.request.urlopen", side_effect=[FakeResponse(issue), FakeResponse(comments)]):
        result = fetch_issue("acme", "widget", 7)
    description = result.as_repair_description()
    assert result.labels == ("bug",)
    assert "Crash on empty input" in description
    assert "Stack trace here" in description


def test_pull_request_is_rejected() -> None:
    with patch("urllib.request.urlopen", return_value=FakeResponse({"pull_request": {}, "comments": 0})):
        with pytest.raises(GitHubError, match="pull request"):
            fetch_issue("acme", "widget", 8)

