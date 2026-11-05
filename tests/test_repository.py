from pathlib import Path

import pytest

from repofix.repository import RepositoryError, acquire_repository, validate_github_repository_url


def test_local_repository_is_copied_by_default(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("VALUE = 1")
    workspace = tmp_path / "jobs"

    acquired = acquire_repository(str(source), workspace)

    assert acquired != source
    assert (acquired / "app.py").read_text() == "VALUE = 1"
    (acquired / "app.py").write_text("VALUE = 2")
    assert (source / "app.py").read_text() == "VALUE = 1"


def test_in_place_returns_original_directory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    assert acquire_repository(str(source), tmp_path / "jobs", isolated=False) == source.resolve()


def test_normalizes_public_github_repository_url() -> None:
    assert (
        validate_github_repository_url("https://www.github.com/openai/example")
        == "https://github.com/openai/example.git"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/openai/example",
        "https://github.com/openai/example/issues/1",
        "https://user:token@github.com/openai/example",
        "https://github.com/openai/example?tab=readme",
        "https://github.com:invalid/openai/example",
    ],
)
def test_rejects_non_repository_github_urls(url: str) -> None:
    with pytest.raises(RepositoryError):
        validate_github_repository_url(url)
