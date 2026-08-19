from pathlib import Path

from opspilot.market_data.evaluation import run_suite


def test_market_data_evaluation_fixture_passes() -> None:
    dataset = Path(__file__).parents[1] / "eval" / "market_data_cases.json"
    result = run_suite(dataset)

    assert result["case_count"] == 6
    assert result["passed_count"] == 6
    assert result["citation_integrity_rate"] == 1.0
    assert result["safety_contract_rate"] == 1.0
