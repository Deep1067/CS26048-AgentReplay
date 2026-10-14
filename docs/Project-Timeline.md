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
| Phase 2 | Deterministic configurable evaluation of recorded session outputs and persisted baseline/fork comparisons, with evidence, versioning, and append-only history |
| Phase 3 | Reusable versioned evaluation suites, safe deterministic assertions, suite-based experiment comparisons, and persisted strict replay validation history |

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
- Generalized experiment execution for arbitrary agent graphs, live event streaming, and
  provider-confirmed billing remain later-phase work.

## Phase 2 deterministic evaluation

- The evaluator applies validated JSON expected-value checks, dotted-path required fields,
  case-insensitive required phrases, recorded error detection/acceptance, and optional latency,
  token, and estimated-cost thresholds. It does not execute user code or call an LLM judge.
- Evaluations are appended to SQLite history with criteria, evaluator version, timestamp, session
  or experiment identifiers, result explanations, and event evidence references.
- Experiment evaluations run the same criteria against the persisted baseline and fork and show
  per-criterion status comparisons; no weighted aggregate hides failed checks.
- The Playground can evaluate a selected recorded session offline. Actual Playground completions
  continue to come only from configured server-side providers and are labeled as provider output.
- Strict replay validity is separate from task/output quality. Session evaluation does not execute
  replay; saved experiment evaluation reports the strict replay evidence already recorded there.
- Efficiency remains descriptive and estimated cost is not provider-confirmed billing.

## Phase 3 reusable evaluation and replay validation

- Named evaluation suites are persisted as immutable versions. Evaluation records keep the suite
  ID/version and the exact normalized criteria snapshot used for that run.
- Deterministic assertions can inspect selected recorded output fields, event results/errors, or
  supported aggregate metrics. Missing evidence is unavailable; no arbitrary user code or LLM
  judge is executed.
- Guided experiment evaluations can apply one suite version to both baseline and fork and report
  per-check status changes without hiding failures in an aggregate score.
- Strict replay validations are persisted independently from quality evaluations. Each validation
  records event-level match, divergence, missing-result, or unchecked evidence and explicitly does
  not rerun an agent.
- Live monitoring remains a session-store refresh rather than an event stream, and scenario
  execution remains disabled unless explicitly enabled by server configuration.
