from __future__ import annotations

import json
from importlib.resources import files

from .domain import MarketDataFixture


BUILTIN_FIXTURES = {
    "us-equity-daily-bars-v1": "data/us_equity_daily_bars_v1.json",
}


def load_fixture(fixture_id: str = "us-equity-daily-bars-v1") -> MarketDataFixture:
    """Load a versioned, package-local fixture without network access."""

    try:
        relative_path = BUILTIN_FIXTURES[fixture_id]
    except KeyError as error:
        raise ValueError(f"unknown market-data fixture: {fixture_id}") from error

    resource = files("opspilot.market_data").joinpath(relative_path)
    return MarketDataFixture.model_validate(json.loads(resource.read_text(encoding="utf-8")))


def list_fixtures() -> list[dict[str, str]]:
    return [
        {
            "fixture_id": fixture.fixture_id,
            "version": fixture.version,
            "dataset": fixture.dataset,
            "provider": fixture.provider,
        }
        for fixture in (load_fixture(fixture_id) for fixture_id in BUILTIN_FIXTURES)
    ]
