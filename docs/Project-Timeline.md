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
| Phase 4 | Bounded, authenticated-when-remote, model-only live runs with incremental session events, persistent run status, configured-model selection, and provider-adapter hardening |
| Phase 5 | Replay Guide connecting recorded traces, persisted strict validation, and supported controlled forks through existing workflows |

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

## Phase 4 bounded live execution

- The Live Monitor launches one explicitly requested call to one configured OpenAI, Anthropic, or
  Gemini model. It does not invoke tools or rerun an arbitrary agent graph. Model choice is limited
  to the model configured for that provider, with a maximum 8,000-character prompt and 1,024-token
  response cap.
- `LIVE_RUN_ENABLED` remains false by default. Loopback requests can use the local development UI
  when enabled. Remote provider execution through Live Run and Playground requires a separate
  server-configured `LIVE_RUN_AUTH_TOKEN`; the token is submitted transiently and is not stored in
  browser storage. Provider API keys remain server-side. Remote pricing/detector updates also remain
  disabled unless enabled, and then require the separate `CONFIG_MUTATIONS_AUTH_TOKEN`.
- Run status and one model-call event are persisted in the existing session/event store. The event
  is written before the provider request, then finalized with the recorded output, reported token
  usage, duration, and configured-rate cost estimate when available. Provider failures retain a
  failed event and terminal `failed` status. The UI polls persisted status; provider output is not
  streamed.
- Provider HTTP calls are limited to 30 seconds, with one in-process provider call at a time and
  no automatic retries. Worker/process interruption can leave a run non-terminal; cross-process
  concurrency and cancellation are not implemented.
- OpenAI requests use the server-side bearer credential; Gemini credentials are sent in a header
  rather than a URL. Responses with missing usage remain unavailable rather than synthesizing
  token counts. Costs are estimates from configured rates, never provider-confirmed billing.
- The API provider catalog returns configured models only. Defaults are `gpt-4o-mini`,
  `claude-3-5-haiku-latest`, and the Gemini `DEFAULT_MODEL`; OpenAI/Anthropic models can be set
  with `OPENAI_MODEL` and `ANTHROPIC_MODEL`.
- No real provider call, deployment, or browser automation is claimed as part of this phase.
  Remote deployment configuration must keep `LIVE_RUN_ENABLED` off unless the separate auth token
  is installed and protected.

## Phase 5 Replay Guide

- The Replay Guide selects from persisted sessions, reports current fork eligibility, and routes
  trace inspection to the existing ordered Traces timeline.
- Strict validation submits to the existing replay-validation endpoint and renders its saved
  evidence and validation history. It validates recorded calls and responses; it does not rerun
  an agent or call a provider.
- For eligible scenario-2 account workflows, the guide shows the recorded first tool response,
  accepts an explicit JSON replacement, and invokes the existing guided experiment operation.
  Server-side validation remains authoritative and the baseline session is not modified.
- Saved validation history and experiment/evaluation history remain accessible from the existing
  Replay and Experiments sections. Session evaluation routes to the existing Playground recorded-
  output evaluator. No duplicate replay engine, trace viewer, evaluator, or persistence store was
  introduced.
- Fork support remains intentionally limited to the recorded account workflow. Arbitrary graph
  replay, additional substitution points, and live model execution remain separate capabilities.
