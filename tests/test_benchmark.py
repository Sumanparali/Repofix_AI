import csv
import json
from pathlib import Path

from repofix.benchmark import run_dataset


def test_benchmark_reports_localization_hit(tmp_path: Path) -> None:
    repository = tmp_path / "project"
    repository.mkdir()
    (repository / "email_validator.py").write_text("def validate_email(value): return value")
    dataset = tmp_path / "cases.json"
    dataset.write_text(json.dumps([{"id": "one", "repository": str(repository), "issue": "email validation bug", "expected_file": "email_validator.py"}]))
    output = tmp_path / "result.csv"
    run_dataset(dataset, output, tmp_path / "work")
    rows = list(csv.DictReader(output.open()))
    assert rows[0]["status"] == "analyzed"
    assert rows[0]["top_k_hit"] == "True"

