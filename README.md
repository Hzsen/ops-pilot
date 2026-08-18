# OpsPilot — Market Data Reliability Copilot

Evidence-grounded incident triage and human-approved runbook automation for market-data pipelines.

## Project status

OpsPilot currently contains a tested, deterministic vertical slice for generic service incidents. The market-data specialization described below is the next product direction; it is not implemented yet.

| Area | Current state | Planned state |
| --- | --- | --- |
| API | FastAPI incident, triage, and approval endpoints | Async jobs, replay endpoints, and incident timelines |
| Reasoning | Deterministic rules with cited evidence | Tool-driven LLM synthesis over the same evidence boundary |
| Storage | In-memory repository | PostgreSQL plus object storage for replay artifacts |
| Domain | Generic logs and service metrics | Prices, volumes, calendars, corporate actions, and feature partitions |
| Safety | Every proposed action requires approval; no executor | Typed tool permissions, dry runs, idempotency, and audited execution |
| Evaluation | Eight offline routing and citation cases | Fault injection, recovery, latency, cost, and policy-violation suites |

Do not describe planned items as completed work. Resume claims should be based only on reproducible tests and saved evaluation results.

## Why this project exists

Market-data failures are often silent. A pipeline may complete while publishing stale, duplicated, unadjusted, or temporally invalid data to a backtest or research system. OpsPilot is intended to answer four operational questions:

1. What failed or became unreliable?
2. Which logs, metrics, lineage records, and quality checks support that conclusion?
3. What is the safest next diagnostic or recovery action?
4. Did the approved recovery restore data correctness without creating a second incident?

The project demonstrates production AI-engineering boundaries rather than another chat interface:

- typed tools and schemas;
- evidence-linked hypotheses;
- explicit human approval;
- replayable incidents and deterministic evaluation;
- observability, failure injection, and recovery measurement;
- a deployable service boundary.

## Target user and representative workflow

The initial user is an engineer or quantitative researcher responsible for a daily equity-data pipeline.

Example incident:

1. The 09:00 ET validation job reports missing bars for 37 symbols and an unusually high split-adjustment ratio for one symbol.
2. OpsPilot retrieves ingestion logs, freshness metrics, the affected partitions, corporate-action records, and the relevant runbook.
3. It produces ranked hypotheses with evidence IDs, such as vendor throttling, a stale trading calendar, or a missing split event.
4. It proposes bounded actions: refetch an explicit symbol/date range, quarantine a partition, or rebuild a named feature table.
5. A human approves or rejects each action.
6. The system records the decision, executes only approved typed actions, reruns validation, and writes an incident report.

## Scope

### In scope

- US-equity daily or minute-bar ingestion failures;
- missing, duplicate, stale, or out-of-order observations;
- timezone and exchange-calendar errors;
- split/dividend adjustment inconsistencies;
- schema drift, provider throttling, and partial writes;
- lineage-aware diagnosis and bounded recovery;
- offline incident replay and synthetic fault injection.

### Non-goals

- selecting securities or recommending trades;
- claiming that an LLM can determine the economic truth of a disputed price;
- unrestricted shell, SQL, or cloud access;
- autonomous production remediation without policy checks and approval;
- replacing conventional validation, alerting, or observability systems.

## Current architecture

```text
Incident logs + metrics
          |
          v
  FastAPI ingestion
          |
          v
Deterministic tool router
  |       |        |
logs   metrics   runbooks
  \       |       /
   evidence packet
          |
          v
cited hypotheses + next checks
          |
          v
human approval audit
```

The deterministic engine is intentional. It establishes testable evidence, citation, and approval contracts before an LLM is allowed into the control path.

## Implemented vertical slice

- `POST /api/incidents`
- `GET /api/incidents/{incident_id}`
- `POST /api/incidents/{incident_id}/triage`
- `POST /api/incidents/{incident_id}/approvals`
- `GET /health`
- pattern-based log search and metric anomaly routing;
- deterministic runbook retrieval;
- evidence IDs required by every supported hypothesis;
- proposed actions whose schema always requires human approval;
- eight-case offline evaluation baseline;
- unit and API integration tests;
- Docker packaging and a GitHub Actions test/evaluation gate.

Approval records are audit events only in the current version. There is no production action executor.

## Repository layout

```text
ops-pilot/
├── .github/workflows/ci.yml
├── eval/cases.json
├── src/opspilot/
│   ├── api.py
│   ├── domain.py
│   ├── evaluation.py
│   ├── repository.py
│   └── triage.py
├── tests/
├── Dockerfile
├── docker-compose.yml
├── Makefile
└── pyproject.toml
```

## Quick start

Requirements: Python 3.11 or later.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/python -m opspilot.evaluation eval/cases.json
.venv/bin/python -m uvicorn opspilot.api:app --reload
```

Or run the service in a container:

```bash
docker compose up --build
```

## Current API example

Create an incident:

```bash
curl -s http://127.0.0.1:8000/api/incidents \
  -H 'content-type: application/json' \
  -d '{
    "title": "Adjusted bars missing after vendor retry",
    "service": "equity-bar-ingestion",
    "logs": ["vendor upstream connection refused"],
    "metrics": {"error_rate": 0.12, "queue_depth": 4200}
  }'
```

Pass the returned `incident_id` to the triage endpoint. The response contains a tool trace, an evidence packet, ranked hypotheses, next checks, and approval-required actions.

## Target market-data architecture

```text
Provider/API + SEC + calendars + corporate actions
                        |
                        v
              ingestion and feature jobs
                        |
          logs + metrics + lineage + data checks
                        |
                        v
                incident event bus
                        |
                        v
             OpsPilot orchestration layer
         /          |          |          \
   log search   data profile   lineage   runbooks
         \          |          |          /
                evidence packet
                        |
          policy engine + human approval
                        |
             typed recovery action runner
                        |
        post-action validation + audit report
```

Candidate tools should be narrow and typed, for example:

- `inspect_partition(dataset, symbols, start, end)`
- `compare_provider_counts(provider, symbols, session)`
- `lookup_corporate_actions(symbol, start, end)`
- `trace_feature_lineage(feature_table, partition)`
- `dry_run_refetch(provider, symbols, start, end)`
- `quarantine_partition(dataset, partition, reason)`
- `rebuild_partition(dataset, partition, idempotency_key)`

The model must never construct arbitrary SQL or shell commands for execution.

## Safety invariants

These are architectural requirements, not optional UI features:

- Untrusted logs and documents are evidence, never instructions.
- Every hypothesis must cite evidence present in the returned packet.
- Every mutating tool call requires an explicit approval record.
- Tool arguments must validate against allowlisted resources and bounded date ranges.
- Every recovery operation needs a dry-run representation and idempotency key.
- The action runner must reject stale approvals and mismatched arguments.
- Post-action validation must run before an incident is marked recovered.
- All model, tool, approval, and validation events must be auditable.

## Evaluation plan

### Diagnosis metrics

- incident detection precision and recall;
- root-cause top-1 and top-3 accuracy;
- required-tool routing accuracy;
- citation integrity and evidence coverage;
- unsupported-claim rate.

### Recovery metrics

- false-remediation rate;
- approval-policy violation rate;
- successful recovery rate;
- post-recovery data-check pass rate;
- mean time to diagnose and mean time to recovery;
- retry/idempotency correctness.

### System metrics

- p50 and p95 triage latency;
- token and tool-call cost per incident;
- queue recovery after worker restart;
- trace completeness;
- concurrent replay throughput.

The initial fault suite should inject missing rows, duplicates, stale timestamps, incorrect split adjustment, schema drift, provider 429/5xx responses, partial writes, and prompt-injection text inside logs.

## Development roadmap

### Phase 0 — Existing baseline

- Preserve the deterministic engine and eight-case regression suite.
- Keep all tests green while introducing domain-specific types.

### Phase 1 — Market-data incident model

- Add dataset, provider, symbol universe, session, partition, and quality-check types.
- Build a small reproducible fixture dataset and fault injector.
- Add calendar, corporate-action, and data-profile tools.

### Phase 2 — Persistence and orchestration

- Replace in-memory state with PostgreSQL.
- Add background jobs, retries, idempotency, and incident timelines.
- Persist evidence snapshots so historical evaluations remain reproducible.

### Phase 3 — Model-assisted synthesis

- Put a provider-agnostic structured LLM behind the existing evidence contract.
- Treat retrieved content as untrusted data.
- Add prompt-injection, abstention, and citation regression cases.

### Phase 4 — Approved execution

- Implement only allowlisted local recovery tools first.
- Require dry run, human approval, argument matching, and post-action validation.
- Add failure injection around partial actions and worker restarts.

### Phase 5 — Delivery and measurement

- Build a compact incident workspace with evidence and approval UX.
- Add OpenTelemetry traces and load tests.
- Publish an evaluation report with fixed dataset/version identifiers.

## Completion criteria for a portfolio release

The project is portfolio-ready when a reviewer can reproduce all of the following:

1. Inject at least five distinct market-data faults.
2. Observe evidence-grounded diagnosis with no unsupported citations.
3. Approve a bounded recovery action and reject an unsafe one.
4. Verify post-recovery data integrity and a complete audit trail.
5. Run tests and the offline evaluation suite from a clean environment.
6. Read benchmark results that distinguish measured facts from future work.

## Resume-claim policy

Do not publish accuracy, latency, recovery, or productivity numbers until the command, fixture version, hardware, and raw result artifact are committed. A future resume bullet should describe the measured system outcome, not the planned architecture.

## Starting point for the next development conversation

Before adding an LLM or UI:

1. inspect the existing API, domain models, tests, and evaluation fixture;
2. run the current test and evaluation suites;
3. define the smallest market-data fixture and fault taxonomy;
4. extend the deterministic evidence boundary first;
5. record the baseline results before implementing model-assisted synthesis.

