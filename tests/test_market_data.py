from datetime import date

import pytest

from opspilot.market_data.domain import FaultSpec, FaultType
from opspilot.market_data.faults import FaultInjectionError, FaultInjector
from opspilot.market_data.fixtures import load_fixture
from opspilot.market_data.triage import MarketDataTriageEngine


@pytest.mark.parametrize(
    ("fault_type", "symbol", "session", "expected_text", "expected_tool", "expected_action"),
    [
        (
            FaultType.MISSING_ROW,
            "AAA",
            date(2025, 1, 2),
            "partition is incomplete",
            "inspect_partition",
            "dry_run_refetch",
        ),
        (
            FaultType.DUPLICATE_ROW,
            "AAA",
            date(2025, 1, 3),
            "duplicate symbol/session",
            "inspect_partition",
            "quarantine_partition",
        ),
        (
            FaultType.STALE_TIMESTAMP,
            "CCC",
            date(2025, 1, 3),
            "does not belong",
            "check_trading_calendar",
            "quarantine_partition",
        ),
        (
            FaultType.INCORRECT_ADJUSTMENT,
            "BBB",
            date(2025, 1, 3),
            "inconsistent with the recorded adjustment factor",
            "lookup_corporate_actions",
            "rebuild_adjustments",
        ),
        (
            FaultType.SCHEMA_DRIFT,
            "CCC",
            date(2025, 1, 2),
            "allowlisted daily-bar schema",
            "inspect_partition",
            "quarantine_partition",
        ),
    ],
)
def test_fault_routes_to_cited_diagnosis_and_typed_action(
    fault_type: FaultType,
    symbol: str,
    session: date,
    expected_text: str,
    expected_tool: str,
    expected_action: str,
) -> None:
    fixture = load_fixture()
    batch = FaultInjector().inject(
        fixture,
        [FaultSpec(fault_type=fault_type, symbol=symbol, session=session)],
    )
    report = MarketDataTriageEngine().triage(batch)

    assert expected_tool in report.tool_trace
    assert any(expected_text in item.statement.casefold() for item in report.hypotheses)
    assert any(item.action_type == expected_action for item in report.proposed_actions)

    evidence_ids = {item.evidence_id for item in report.evidence}
    assert all(
        evidence_id in evidence_ids
        for hypothesis in report.hypotheses
        for evidence_id in hypothesis.evidence_ids
    )
    assert all(
        action.requires_approval and action.dry_run and action.idempotency_key
        for action in report.proposed_actions
    )


def test_clean_fixture_is_a_no_action_baseline() -> None:
    fixture = load_fixture()
    report = MarketDataTriageEngine().triage(FaultInjector().inject(fixture, []))

    assert report.proposed_actions == []
    assert "no supported" in report.hypotheses[0].statement.casefold()
    assert report.hypotheses[0].evidence_ids


def test_fault_output_and_action_ids_are_deterministic() -> None:
    fixture = load_fixture()
    faults = [
        FaultSpec(
            fault_type=FaultType.MISSING_ROW,
            symbol="AAA",
            session=date(2025, 1, 2),
        )
    ]
    injector = FaultInjector()
    engine = MarketDataTriageEngine()

    first = engine.triage(injector.inject(fixture, faults))
    second = engine.triage(injector.inject(fixture, faults))

    assert first == second
    assert first.proposed_actions[0].idempotency_key == second.proposed_actions[0].idempotency_key


def test_adjustment_fault_rejects_non_action_target() -> None:
    fixture = load_fixture()

    with pytest.raises(FaultInjectionError, match="corporate action"):
        FaultInjector().inject(
            fixture,
            [
                FaultSpec(
                    fault_type=FaultType.INCORRECT_ADJUSTMENT,
                    symbol="AAA",
                    session=date(2025, 1, 2),
                )
            ],
        )
