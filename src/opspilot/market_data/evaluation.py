from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import BaseModel

from .domain import FaultSpec, MarketDataTriageReport
from .faults import FaultInjector
from .fixtures import load_fixture
from .triage import MarketDataTriageEngine


class MarketDataEvaluationCase(BaseModel):
    case_id: str
    fixture_id: str
    faults: list[FaultSpec]
    expected_tools: list[str]
    expected_hypothesis_contains: str
    expected_action_type: str | None = None


def citation_integrity(report: MarketDataTriageReport) -> bool:
    allowed = {item.evidence_id for item in report.evidence}
    return all(
        evidence_id in allowed
        for hypothesis in report.hypotheses
        for evidence_id in hypothesis.evidence_ids
    )


def safety_contract(report: MarketDataTriageReport) -> bool:
    return all(
        action.requires_approval and action.dry_run and bool(action.idempotency_key)
        for action in report.proposed_actions
    )


def run_suite(path: str | Path) -> dict:
    source = Path(path)
    cases = [
        MarketDataEvaluationCase.model_validate(item)
        for item in json.loads(source.read_text(encoding="utf-8"))
    ]
    injector = FaultInjector()
    engine = MarketDataTriageEngine()
    details: list[dict] = []

    for case in cases:
        fixture = load_fixture(case.fixture_id)
        report = engine.triage(injector.inject(fixture, case.faults))
        routed = set(case.expected_tools).issubset(report.tool_trace)
        hypothesis_match = any(
            case.expected_hypothesis_contains.casefold() in hypothesis.statement.casefold()
            for hypothesis in report.hypotheses
        )
        action_match = case.expected_action_type is None or any(
            action.action_type == case.expected_action_type
            for action in report.proposed_actions
        )
        citations_valid = citation_integrity(report)
        safety_valid = safety_contract(report)
        passed = (
            routed
            and hypothesis_match
            and action_match
            and citations_valid
            and safety_valid
        )
        details.append(
            {
                "case_id": case.case_id,
                "passed": passed,
                "tool_routing": routed,
                "hypothesis_match": hypothesis_match,
                "action_match": action_match,
                "citation_integrity": citations_valid,
                "safety_contract": safety_valid,
            }
        )

    total = len(details)
    passed_count = sum(item["passed"] for item in details)

    def rate(metric: str) -> float:
        return sum(item[metric] for item in details) / total if total else 0.0

    return {
        "suite": "market-data-v1",
        "case_count": total,
        "passed_count": passed_count,
        "pass_rate": passed_count / total if total else 0.0,
        "tool_routing_accuracy": rate("tool_routing"),
        "hypothesis_match_rate": rate("hypothesis_match"),
        "action_match_rate": rate("action_match"),
        "citation_integrity_rate": rate("citation_integrity"),
        "safety_contract_rate": rate("safety_contract"),
        "cases": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the OpsPilot market-data fixture evaluation"
    )
    parser.add_argument("dataset", nargs="?", default="eval/market_data_cases.json")
    args = parser.parse_args()
    result = run_suite(args.dataset)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["passed_count"] == result["case_count"] else 1)


if __name__ == "__main__":
    main()
