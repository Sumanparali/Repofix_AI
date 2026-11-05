from pathlib import Path

from repofix.models import ProjectProfile
from repofix.static_scan import scan_repository


def test_static_scan_reports_local_code_findings(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        'API_KEY = "not-a-real-secret"\ntry:\n    run()\nexcept:\n    pass  # TODO fix\n'
    )

    findings = scan_repository(tmp_path, ProjectProfile("python", None, None))
    titles = {finding["title"] for finding in findings}

    assert "Possible hard-coded secret" in titles
    assert "Bare exception handler" in titles
    assert "Unresolved maintenance marker" in titles
    assert "No automated tests detected" in titles
