.PHONY: install test eval run

install:
	.venv/bin/python -m pip install -e '.[dev]'

test:
	.venv/bin/python -m pytest

eval:
	.venv/bin/python -m opspilot.evaluation eval/cases.json

run:
	.venv/bin/python -m uvicorn opspilot.api:app --reload
