# Requirements

## Functional requirements

- Record model and tool calls within a named session.
- Store call inputs, outputs, errors, sequence numbers, duration, token usage, and estimated model cost.
- Display recorded sessions and event timelines through the web interface.
- Replay recorded traces in strict mode without invoking live tool/model functions for explicit wrappers.
- Detect argument, name, type, order, and unrecorded-call divergence.
- Support forked replay with tool-response substitution.
- Detect repeated tool calls, high-cost sessions, long sessions, and excessive event counts.
- Display and edit configured model pricing in INR per 1K tokens and persist it to `prices.json`.
- Display and edit detector thresholds and persist them to detector configuration.
- Restrict browser access through the configured local CORS origins and safely render recorded values.

## Non-functional requirements

- Python 3.11 or newer.
- Local SQLite storage with no mandatory hosted services.
- Deterministic strict replay must not fabricate missing responses.
- The interface should remain usable on desktop and smaller screens.
- Automated tests should cover storage, interception, replay, API behavior, pricing, and detector rules.

## Scope boundaries

- Single-agent workflows only.
- Two or three tools in the demonstration integrations.
- Rule-based detection only; no ML anomaly model.
- No automated root-cause diagnosis.
- LangGraph model calls are recorded for audit and cost tracking, but live model execution during LangGraph replay remains a known limitation.
