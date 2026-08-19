from __future__ import annotations

import hashlib
from collections import Counter
from datetime import date
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from .domain import (
    DailyBar,
    FindingCategory,
    MarketDataBatch,
    ToolFinding,
    ToolResult,
)


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _finding(
    *,
    category: FindingCategory,
    source_type: str,
    source_ref: str,
    excerpt: str,
    symbols: list[str] | None = None,
    sessions: list[date] | None = None,
) -> ToolFinding:
    identity = f"{source_type}:{source_ref}:{category}:{excerpt}"
    return ToolFinding(
        finding_id=_stable_id("finding", identity),
        category=category,
        source_type=source_type,
        source_ref=source_ref,
        excerpt=excerpt,
        affected_symbols=symbols or [],
        affected_sessions=sessions or [],
    )


def _row_key(row: dict) -> tuple[str, date] | None:
    try:
        return str(row["symbol"]), date.fromisoformat(str(row["session"]))
    except (KeyError, TypeError, ValueError):
        return None


class DataProfileTool:
    name = "inspect_partition"

    def run(self, batch: MarketDataBatch) -> ToolResult:
        findings: list[ToolFinding] = []
        required_fields = set(DailyBar.model_fields)
        parsed_rows: list[tuple[int, DailyBar]] = []

        for index, row in enumerate(batch.rows):
            actual_fields = set(row)
            missing_fields = sorted(required_fields - actual_fields)
            unexpected_fields = sorted(actual_fields - required_fields)
            if missing_fields or unexpected_fields:
                key = _row_key(row)
                symbol = key[0] if key else None
                session = key[1] if key else None
                findings.append(
                    _finding(
                        category=FindingCategory.SCHEMA_DRIFT,
                        source_type="data_profile",
                        source_ref=f"rows[{index}]",
                        excerpt=(
                            f"schema mismatch: missing={missing_fields}, "
                            f"unexpected={unexpected_fields}"
                        ),
                        symbols=[symbol] if symbol else [],
                        sessions=[session] if session else [],
                    )
                )
                continue
            try:
                parsed_rows.append((index, DailyBar.model_validate(row)))
            except ValidationError as error:
                key = _row_key(row)
                findings.append(
                    _finding(
                        category=FindingCategory.SCHEMA_DRIFT,
                        source_type="data_profile",
                        source_ref=f"rows[{index}]",
                        excerpt=f"row violates the daily-bar contract: {error.error_count()} error(s)",
                        symbols=[key[0]] if key else [],
                        sessions=[key[1]] if key else [],
                    )
                )

        raw_keys = [key for row in batch.rows if (key := _row_key(row)) is not None]
        counts = Counter(raw_keys)
        duplicate_keys = sorted(key for key, count in counts.items() if count > 1)
        for symbol, session in duplicate_keys:
            findings.append(
                _finding(
                    category=FindingCategory.DUPLICATE_ROW,
                    source_type="data_profile",
                    source_ref=f"partition/{session.isoformat()}/{symbol}",
                    excerpt=(
                        f"duplicate symbol/session key: symbol={symbol}, "
                        f"session={session.isoformat()}, count={counts[(symbol, session)]}"
                    ),
                    symbols=[symbol],
                    sessions=[session],
                )
            )

        expected_keys = {
            (symbol, session)
            for symbol in batch.expected_symbols
            for session in batch.sessions
        }
        missing_keys = sorted(expected_keys - set(raw_keys))
        for symbol, session in missing_keys:
            findings.append(
                _finding(
                    category=FindingCategory.MISSING_ROW,
                    source_type="data_profile",
                    source_ref=f"partition/{session.isoformat()}/{symbol}",
                    excerpt=(
                        f"expected symbol/session key is absent: symbol={symbol}, "
                        f"session={session.isoformat()}"
                    ),
                    symbols=[symbol],
                    sessions=[session],
                )
            )

        for index, row in parsed_rows:
            expected_adjusted_close = row.close * row.adjustment_factor
            if abs(row.adjusted_close - expected_adjusted_close) > 1e-8:
                findings.append(
                    _finding(
                        category=FindingCategory.INCORRECT_ADJUSTMENT,
                        source_type="data_profile",
                        source_ref=f"rows[{index}]",
                        excerpt=(
                            f"adjusted_close={row.adjusted_close:g}, expected="
                            f"{expected_adjusted_close:g} from close={row.close:g} and "
                            f"adjustment_factor={row.adjustment_factor:g}"
                        ),
                        symbols=[row.symbol],
                        sessions=[row.session],
                    )
                )

        if not findings:
            findings.append(
                _finding(
                    category=FindingCategory.CLEAN_PROFILE,
                    source_type="data_profile",
                    source_ref=f"fixtures/{batch.fixture_id}",
                    excerpt=(
                        f"profile matched {len(expected_keys)} expected keys; "
                        "no schema, completeness, duplicate, or adjustment anomaly found"
                    ),
                )
            )
        return ToolResult(tool_name=self.name, findings=findings)


class TradingCalendarTool:
    name = "check_trading_calendar"

    def run(self, batch: MarketDataBatch) -> ToolResult:
        findings: list[ToolFinding] = []
        timezone = ZoneInfo(batch.timezone)

        for index, raw_row in enumerate(batch.rows):
            try:
                row = DailyBar.model_validate(raw_row)
            except ValidationError:
                continue
            observed_session = row.timestamp.astimezone(timezone).date()
            if observed_session != row.session:
                findings.append(
                    _finding(
                        category=FindingCategory.STALE_TIMESTAMP,
                        source_type="calendar",
                        source_ref=f"rows[{index}].timestamp",
                        excerpt=(
                            f"timestamp resolves to {observed_session.isoformat()} in "
                            f"{batch.timezone}, but row session is {row.session.isoformat()}"
                        ),
                        symbols=[row.symbol],
                        sessions=[row.session],
                    )
                )
        return ToolResult(tool_name=self.name, findings=findings)


class CorporateActionTool:
    name = "lookup_corporate_actions"

    def run(
        self,
        batch: MarketDataBatch,
        symbols: set[str],
        sessions: set[date],
    ) -> ToolResult:
        findings = [
            _finding(
                category=FindingCategory.CORPORATE_ACTION,
                source_type="corporate_action",
                source_ref=f"corporate-actions/{action.symbol}/{action.ex_date.isoformat()}",
                excerpt=(
                    f"split_ratio={action.split_ratio:g}, expected_adjustment_factor="
                    f"{action.expected_adjustment_factor:g}"
                ),
                symbols=[action.symbol],
                sessions=[action.ex_date],
            )
            for action in batch.corporate_actions
            if action.symbol in symbols and action.ex_date in sessions
        ]
        return ToolResult(tool_name=self.name, findings=findings)
