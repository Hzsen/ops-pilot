.PHONY: install test eval market-eval run

install:
	.venv/bin/python -m pip install -e '.[dev]'

test:
	.venv/bin/python -m pytest

eval:
	.venv/bin/python -m opspilot.evaluation eval/cases.json

market-eval:
	.venv/bin/python -m opspilot.market_data.evaluation eval/market_data_cases.json

run:
	.venv/bin/python -m uvicorn opspilot.api:app --reload
