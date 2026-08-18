from pathlib import Path

from opspilot.evaluation import run_suite


def test_offline_evaluation_fixture_passes() -> None:
    dataset = Path(__file__).parents[1] / "eval" / "cases.json"
    result = run_suite(dataset)

    assert result["case_count"] == 8
    assert result["passed_count"] == 8
    assert result["citation_integrity_rate"] == 1.0

