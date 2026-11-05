from pathlib import Path

from repofix.retriever import issue_terms, retrieve_relevant_files


def test_issue_terms_removes_common_words() -> None:
    assert "the" not in issue_terms("The parser crashes when parsing an empty token")
    assert "parser" in issue_terms("The parser crashes when parsing an empty token")


def test_retrieval_ranks_matching_source(tmp_path: Path) -> None:
    (tmp_path / "email_validator.py").write_text("def validate_email(email): return True")
    (tmp_path / "unrelated.py").write_text("def calculate_total(): return 0")
    matches = retrieve_relevant_files(tmp_path, "email validation fails for empty email")
    assert matches
    assert matches[0].path == Path("email_validator.py")


def test_retrieval_ignores_virtual_environment(tmp_path: Path) -> None:
    ignored = tmp_path / ".venv" / "email.py"
    ignored.parent.mkdir()
    ignored.write_text("email email email")
    assert retrieve_relevant_files(tmp_path, "email failure") == []

