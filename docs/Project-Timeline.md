# Project Timeline

| Phase | Work completed |
|---|---|
| M0 | Project setup, session context, and core event model |
| M1 | SQLite session and event storage |
| M2 | Token and model-cost tracking with configurable pricing |
| M3 | FastAPI backend and timeline web UI |
| M4 | Strict replay, divergence detection, and forked tool replay |
| M5 | Rule-based anomaly detection and timeline flags |
| M6 | LangGraph and Google GenAI/ADK-style integrations plus failure scenarios |
| M7 | Replay API, four-tab UI, editable pricing, cost history, and detector settings |
| M8 | Security hardening, DOM-safe rendering, CORS restriction, testing, and documentation |
| Phase 1 foundation | Persisted guided comparisons from supported recorded sessions, explicit usage/cost availability, connected section navigation, and live-monitor capability reporting |

## Current status

The local implementation is functional and validated by the automated test suite. Production deployment, hosted storage, multi-agent tracing, and complete LangGraph model-call substitution remain future work.

## Phase 1 connected-workflow foundation

- Guided experiments can select supported scenario-2 account-workflow sessions, substitute the
  first tool response, strict-replay the recorded baseline, execute the supported fork workflow,
  compare recorded events, and revisit persisted experiment results.
- Usage records are attributed to their source session and model. Missing tokens or rates remain
  unavailable; configured-rate cost values are estimates rather than provider-confirmed bills.
- The primary workspace sections use a collapsible sidebar and retain the selected session as
  navigation context.
- The Live Monitor refreshes the configured session store periodically. It does not report agent
  running state or stream events. Server-defined scenario execution remains disabled unless
  `LIVE_RUN_ENABLED` is enabled.
- Generalized experiment execution for arbitrary agent graphs, live event streaming, configured
  quality evaluators, and provider-confirmed billing remain later-phase work.
