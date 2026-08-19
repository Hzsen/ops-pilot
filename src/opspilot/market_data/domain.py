from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain import Evidence, Hypothesis


class FaultType(StrEnum):
    MISSING_ROW = "missing_row"
    DUPLICATE_ROW = "duplicate_row"
    STALE_TIMESTAMP = "stale_timestamp"
    INCORRECT_ADJUSTMENT = "incorrect_adjustment"
    SCHEMA_DRIFT = "schema_drift"


class FindingCategory(StrEnum):
    MISSING_ROW = "missing_row"
    DUPLICATE_ROW = "duplicate_row"
    STALE_TIMESTAMP = "stale_timestamp"
    INCORRECT_ADJUSTMENT = "incorrect_adjustment"
    SCHEMA_DRIFT = "schema_drift"
    CLEAN_PROFILE = "clean_profile"
    CORPORATE_ACTION = "corporate_action"


class DailyBar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,14}$")
    session: date
    timestamp: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    adjusted_close: float = Field(gt=0)
    adjustment_factor: float = Field(gt=0)
    volume: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_price_range(self) -> DailyBar:
        if self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must include a timezone offset")
        if self.low > min(self.open, self.close) or self.high < max(
            self.open, self.close
        ):
            raise ValueError("OHLC values fall outside the high/low range")
        if self.low > self.high:
            raise ValueError("low must not exceed high")
        return self


class CorporateAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    ex_date: date
    action_type: Literal["split"]
    split_ratio: float = Field(gt=0)
    expected_adjustment_factor: float = Field(gt=0)


class MarketDataFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_id: str
    version: str
    dataset: str
    provider: str
    exchange: str
    timezone: str
    expected_symbols: list[str] = Field(min_length=1)
    sessions: list[date] = Field(min_length=1)
    rows: list[DailyBar] = Field(min_length=1)
    corporate_actions: list[CorporateAction] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_clean_fixture(self) -> MarketDataFixture:
        expected = {
            (symbol, session)
            for symbol in self.expected_symbols
            for session in self.sessions
        }
        actual = {(row.symbol, row.session) for row in self.rows}
        if len(actual) != len(self.rows):
            raise ValueError("fixture rows must have unique symbol/session keys")
        if actual != expected:
            raise ValueError("fixture must contain every expected symbol/session key")
        rows_by_key = {(row.symbol, row.session): row for row in self.rows}
        for action in self.corporate_actions:
            key = (action.symbol, action.ex_date)
            if key not in rows_by_key:
                raise ValueError("corporate action must target a fixture row")
            if (
                abs(
                    rows_by_key[key].adjustment_factor
                    - action.expected_adjustment_factor
                )
                > 1e-8
            ):
                raise ValueError(
                    "fixture adjustment factor must match the corporate-action record"
                )
        return self


class FaultSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fault_type: FaultType
    symbol: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9.\-]{0,14}$")
    session: date | None = None


class MarketDataBatch(BaseModel):
    fixture_id: str
    fixture_version: str
    dataset: str
    provider: str
    exchange: str
    timezone: str
    expected_symbols: list[str]
    sessions: list[date]
    rows: list[dict[str, Any]]
    corporate_actions: list[CorporateAction]
    injected_faults: list[FaultSpec] = Field(default_factory=list)


class ToolFinding(BaseModel):
    finding_id: str
    category: FindingCategory
    source_type: Literal["data_profile", "calendar", "corporate_action"]
    source_ref: str
    excerpt: str = Field(min_length=1, max_length=500)
    affected_symbols: list[str] = Field(default_factory=list)
    affected_sessions: list[date] = Field(default_factory=list)


class ToolResult(BaseModel):
    tool_name: str
    findings: list[ToolFinding]


class RefetchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset: str
    symbols: list[str] = Field(min_length=1)
    start: date
    end: date

    @model_validator(mode="after")
    def validate_range(self) -> RefetchArguments:
        if self.start > self.end:
            raise ValueError("start must not be after end")
        return self


class QuarantineArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str
    partition: str
    reason: str


class RebuildArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str
    partition: str
    symbols: list[str] = Field(min_length=1)


class MarketDataProposedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    action_type: Literal[
        "dry_run_refetch", "quarantine_partition", "rebuild_adjustments"
    ]
    description: str
    arguments: RefetchArguments | QuarantineArguments | RebuildArguments
    dry_run: Literal[True] = True
    idempotency_key: str
    requires_approval: Literal[True] = True

    @model_validator(mode="after")
    def validate_argument_contract(self) -> MarketDataProposedAction:
        expected_type = {
            "dry_run_refetch": RefetchArguments,
            "quarantine_partition": QuarantineArguments,
            "rebuild_adjustments": RebuildArguments,
        }[self.action_type]
        if not isinstance(self.arguments, expected_type):
            raise ValueError(f"{self.action_type} received mismatched arguments")
        return self


class MarketDataTriageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_id: Literal["us-equity-daily-bars-v1"] = "us-equity-daily-bars-v1"
    faults: list[FaultSpec] = Field(default_factory=list, max_length=5)


class MarketDataTriageReport(BaseModel):
    fixture_id: str
    fixture_version: str
    dataset: str
    injected_faults: list[FaultSpec]
    tool_trace: list[str]
    evidence: list[Evidence]
    hypotheses: list[Hypothesis]
    next_checks: list[str]
    proposed_actions: list[MarketDataProposedAction]

    @model_validator(mode="after")
    def validate_citation_boundary(self) -> MarketDataTriageReport:
        allowed = {item.evidence_id for item in self.evidence}
        cited = {
            evidence_id
            for hypothesis in self.hypotheses
            for evidence_id in hypothesis.evidence_ids
        }
        unknown = sorted(cited - allowed)
        if unknown:
            raise ValueError(f"hypotheses cite unknown evidence IDs: {unknown}")
        return self
