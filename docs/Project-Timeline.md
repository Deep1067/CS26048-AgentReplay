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
| Phase 6 | Visual identity, responsive shell and pages, reduced motion, focus states, and keyboard-accessible session selection |
| Phase 7 | Integration, security, persistence, and release-readiness audit; local evidence collected, deployment blockers documented |
| Phase 8 | Release hardening: application access control, explicit deployment storage, readiness probes, bounded timed-out workers, and dependency fixes |
| Phase 9 | Local private-staging preparation and isolated release verification; remote staging blocked pending target-owner review and authorization |

## Current status

The local implementation is functional and validated by the automated test suite. Hosted storage and deployment support exist but have not been verified in a deployed environment. Multi-agent tracing and complete LangGraph model-call substitution remain future work.

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

## Phase 6 visual identity and motion

- Refined the existing dark visual system with reusable color, typography, spacing, radius, shadow,
  focus, and motion tokens; standardized shared page, status, form, table, and timeline treatments.
- Preserved the collapsible sidebar, all existing sections, and the one-selected-panel navigation
  model. The session picker exposes button semantics, keyboard focus, Enter/Space activation, and
  its current selection to assistive technology.
- Kept motion brief and disabled it under `prefers-reduced-motion`. Responsive layouts retain
  bounded horizontal scrolling for wide cost tables instead of creating document-level overflow.
- Automated verification: the session-picker and empty-trace wiring tests and full suite passed
  after these final audit fixes (106 tests; one upstream Google GenAI deprecation warning). Ruff
  lint, Ruff format check, JavaScript syntax check, and `git diff --check` passed.
- Browser verification covered all nine sections at 1440px and 390px, Replay Guide layout at
  1024px and 768px, navigation state, mobile Escape/focus return, and reduced-motion computed
  durations. Key text and status-token pairs measured at 6.94:1 or higher against their dark
  surfaces. The session list loaded from isolated SQLite fixtures. Mouse, Enter, and Space
  activation each selected one row with visible keyboard focus. Trace success output, recorded
  errors, empty-session messaging, strict replay validation/history, experiment and evaluation
  history screens, and actual/estimated/unavailable usage/cost states were inspected in-browser.
  Strict validation and a recorded-output evaluation were saved only to the disposable fixture
  database; no provider calls or existing-data mutations were performed.
- The initial loading failure exposed a storage-selection defect: configured Turso credentials
  took precedence over an explicit temporary `DB_PATH`. The Phase 7 audit fixes that precedence;
  with an explicit local path, the isolated server uses SQLite even if Turso credentials exist.
- Screen-reader behavior, exhaustive component-state contrast measurements, and real provider
  execution remain unverified; no provider call was needed for the Phase 6 browser checks.

## Phase 7 integration, security, and release-readiness audit

- Local SQLite storage selection now honors an explicit non-empty `DB_PATH` before considering
  Turso credentials. If no local path is selected, a partial Turso URL/token configuration fails
  clearly instead of silently falling back to local SQLite. Focused tests cover both cases.
- Existing automated tests exercise session/event retrieval, persisted evaluation-suite versions
  and evaluation/replay history, strict replay evidence, controlled experiments, unavailable usage
  and cost, Live Run defaults and limits, mocked provider failures, remote execution/configuration
  token gates, and invalid input. A disposable SQLite browser smoke test opened all nine sections,
  inspected successful and failed trace events and the empty-session state, saved strict replay
  history, created and compared a deterministic controlled fork, and evaluated the baseline/fork
  through the existing UI. Those validation, experiment, and evaluation writes were confined to
  the disposable database; no provider call or external database was used.
- The browser smoke test verified Enter and Space session selection with exactly one selected row,
  trace output/error rendering, Replay Guide strict-validation history, baseline/fork comparison
  and evaluation-history rendering, and unavailable usage/cost messaging. At 390px, the trace and
  cost views had no document/body horizontal overflow. All nine sections opened at desktop width;
  browser console errors and failed requests were not observed. The UI made only GET requests until
  the explicitly invoked local validation, experiment, and evaluation operations.
- Final local checks passed: 109 pytest tests, Ruff lint, Ruff format check, JavaScript syntax
  check, and `git diff --check`.
- The earlier 106-test baseline reported an upstream Google GenAI deprecation warning. No
  dependency upgrade or vulnerability scan was performed; dependency/CVE clearance remains
  unverified.
- Provider adapters keep keys server-side and cap prompts at 8,000 characters, output at 1,024
  tokens, HTTP timeouts at 30 seconds, and concurrent calls at one per application process.
  Provider verification was mocked only; there was no real provider call. The process-local
  concurrency cap is not a cross-worker limit.
- Fixed-scenario timeout responses are covered with a simulated-delay test, not a blocking worker
  test. `asyncio.wait_for` cannot terminate a synchronous `asyncio.to_thread` worker after timeout;
  the fixed scenario remains step-capped at five calls, but hard worker cancellation is not
  implemented.
- Configuration mutation and remote provider execution have separate server-side tokens and are
  disabled by default. These controls are covered by API tests, but the client-address behavior
  has not been verified behind the Vercel deployment proxy. Session-reading APIs have no general
  user authentication; the deployment must remain private or use an authenticated access layer.
- Local SQLite was exercised with disposable data. Turso, Vercel, cross-invocation persistence,
  deployed startup/health behavior, and production migration were not tested. The app has no
  dedicated health/readiness endpoint. README now records these blockers and a deployment
  verification checklist. Phase 7 is therefore only partially verified and the project is not
  declared release-ready.

## Phase 8 release hardening and deployment readiness

- Vercel startup now requires both Turso credentials and rejects an environment `DB_PATH` override,
  preventing configured remote credentials from masking an accidental ephemeral SQLite selection.
  Outside Vercel, explicit DB_PATH precedence and partial-Turso validation remain intact. Direct
  SQLite construction remains available for local development and isolated tests. A legacy SQLite
  schema migration test covers added event and evaluation columns.
- Vercel startup also requires an application username and a password of at least 24 characters.
  HTTP Basic authentication gates the UI, static assets, OpenAPI, and API routes. Only `/healthz`
  and `/readyz` are public: the first indicates process health, while the second probes storage and
  returns no connection detail. Local development remains unauthenticated unless credentials are
  configured.
- Provider and configuration-mutation tokens are separate from application authentication and use
  dedicated transient `X-Live-Run-Token` and `X-Config-Mutations-Token` headers in the UI. Legacy
  bearer-token authorization remains accepted only when application authentication is not active.
  Privileged actions no longer trust client-address/forwarded headers by default. The explicit
  loopback override is disabled by default and ignored on Vercel.
- Fixed scenario execution is limited to one worker per app instance. A timeout sets a cooperative
  cancellation flag that prevents additional session/event writes; the slot is held until the
  worker returns. Python cannot forcibly stop a blocking tool or provider call already in progress.
  Model-only execution keeps its existing one-call semaphore and default-off setting. No real
  provider call was made.
- The installed environment audit found vulnerable AnyIO and Starlette versions. Project dependency
  floors were raised to FastAPI 0.140.0, Starlette 1.3.1, and AnyIO 4.14.2; these were installed
  and the existing test suite was rerun after the major Starlette 1.x compatibility transition.
  `pip-audit -r requirements.txt` reported no known vulnerabilities for the resolved project
  dependency set. A broader `--local` scan also reported packages not declared in project manifests
  (including pip, Pillow, python-multipart, and setuptools); those environment findings were not
  included in the project dependency resolution and were not upgraded.
- The isolated full test suite passes 124 tests, including access-control success/failure,
  independent privileged tokens, forwarded-header non-bypass, health/readiness behavior, SQLite
  migration, a timeout worker that cannot persist events after cancellation, and provider-failure
  credential non-disclosure in API responses and logs. Provider failure responses are generic;
  logs retain only exception type and run context. Ruff, formatting, JavaScript syntax, diff
  whitespace, and installed dependency consistency checks pass.
  `pip-audit -r requirements.txt` reports no known vulnerabilities in the resolved project
  dependency set. A local browser smoke used fresh temporary SQLite: workspace navigation and empty
  session/trace views loaded, Live Run remained disabled without provider configuration, and the
  390px viewport had no horizontal overflow with reduced-motion preference enabled. No
  session-backed browser workflows were exercised; the previously reported Phase 7 browser checks
  were also local-only. No Turso database, Vercel deployment, or deployment-proxy behavior was
  verified.
- One earlier test-collection attempt loaded `.env`, selected its configured Turso database during
  module-level app initialization, and failed after the remote disconnected. Idempotent schema DDL
  may have run before the failure. The remote database was not revisited; an operator must review
  that staging/remote database's schema and audit trail before attempting deployment validation.
- Phase 8 is not release verification. Before release, deploy privately to non-production Vercel,
  validate app authentication and health probes through the platform, verify cross-invocation
  Turso persistence and intended database selection, test privileged controls and worker timeout
  behavior through the deployed proxy, and repeat the dependency scan against the deployment
  resolution. Do not expose the app publicly until these checks pass.

## Phase 9 private staging and release verification

- Repository state was checked before verification: branch `main`, upstream `origin/main`, and
  local/remote `main` and `master` refs at `8c6c96b`. Existing Phase 6-8 changes and unrelated
  untracked weekly-report/UI-reference files were preserved. No files were staged, committed, or
  pushed.
- Database safety boundary: an ignored repository `.env` exists but was not opened or used. The
  current process had no Turso URL/token values and there was no confirmed, separately provisioned
  staging target or authorization. No remote database or deployment operation was attempted. The
  Phase 8 warning remains: its failed initialization attempt may have applied idempotent schema DDL
  to the previously configured database, which must be reviewed by its owner before any reuse.
- A local app instance ran with `PYTHON_DOTENV_DISABLED=true`, an explicitly selected temporary
  SQLite database, and no provider credentials. Four deterministic sessions included an empty
  session, a trace with a recorded error/output, a fork-eligible recorded account failure, and a
  model call with unavailable usage/cost.
- Browser verification exercised all nine workspace sections; mouse session selection; Enter and
  Space selection; one selected row and retained visible keyboard focus; failed trace/error/output
  rendering; the empty-session state; strict replay of the recorded error (`passed`, with
  `matched_recorded_error` evidence); saved strict-replay history; controlled fork comparison
  (`credit_limit: 1250`); and saved evaluation history (baseline failed, fork passed under the
  configured criteria). Usage displayed unavailable tokens and cost rather than zero. Live Run
  remained disabled with no configured provider. No real provider was called.
- At 390px, document and body widths matched the viewport; reduced-motion preference was active
  and the sidebar transition was reduced to `0.01ms`. No browser console errors or failed app/API
  requests occurred during the recorded workflow. The initial automatic `/favicon.ico` request
  returned 404; no application/API endpoint returned an error.
- After stopping the app, a separate Python process reopened the same disposable local SQLite file
  and confirmed sessions, the saved fork, strict-replay history, and evaluation history persisted.
  This verifies local SQLite only, not Turso or cross-invocation Vercel persistence.
- Local verification: `python -m pytest -q` passed 124 tests; Ruff lint/format, JavaScript syntax,
  `git diff --check`, and `pip check` passed. The project-scoped
  `python -m pip_audit -r requirements.txt --progress-spinner off` found no known vulnerabilities
  in the declared dependency resolution. Provider limits, timeout/cancellation, failure recording,
  and credential redaction are covered by mocked/local tests. Python cannot forcibly terminate a
  blocking worker thread; the request may time out while that operation continues.
- Release status remains blocked. Vercel/Turso, private deployment authentication, readiness via
  deployment probes, forwarded-proxy behavior, general API rate limiting, and remote persistence
  were not verified. The app has no general per-user/per-IP rate limiter; keep deployment private
  behind the intended access boundary and configure edge rate controls before broader exposure.
- Before any remote operation, the database owner must review the previously targeted database's
  schema/audit history. Then provision a distinct non-production Turso database and authorize its
  use; securely provide credentials through a private staging configuration, verify the target
  without printing secrets, leave `DB_PATH` unset, and verify persistence across separate
  invocations. This is a hard gate; no remote connection or deployment is authorized by the
  checklist itself. After authorization, the README's manual staging checklist covers fail-closed
  configuration, cross-invocation session/event/replay/evaluation persistence, database failure
  behavior, Basic auth, privileged-token denial/authorization, health/readiness disclosure,
  forwarded-header spoofing, edge rate controls, execution limits, dependency audit, and safe
  disposal of synthetic data. Keep provider execution disabled and do not use production
  data/credentials or call real providers.

## Performance investigation and targeted optimization

- No Turso or Vercel access was used. A local fixture with 80 synthetic sessions and 1,200 events
  was measured using five TestClient requests per endpoint and SQLite statement tracing. Before the
  changes, `GET /api/sessions` performed 81 reads (27.92 ms median; 15,521 response bytes) and
  `GET /api/overview` performed 331 reads (139.97 ms; 1,128 bytes). Afterward, each endpoint
  performs one grouped read (6.12 ms and 5.22 ms median respectively) with unchanged response
  sizes. A selected-session detail request remained three reads and 9,857 bytes (6.95 ms before,
  6.14 ms after).
- Confirmed API bottleneck: session listing read complete event rows separately for every session
  only to calculate cost status. Overview then loaded session details and event rows repeatedly,
  and detector evaluation queried session summaries again. The grouped storage query now provides
  the API's list and overview metrics in one database operation while preserving summary output,
  unavailable/estimated/actual cost behavior, and detector raw-cost data. The query plan uses the
  existing `idx_events_session_seq`; it still uses temporary B-trees for grouping and ordering.
- Confirmed frontend request amplification: the browser initially made seven API requests,
  including a hidden first-session trace, fork baseline data, and three validation-history
  requests; it now makes two for the default Overview. Session selection dropped from seven API
  requests to one full trace request. Replay, Replay Guide, and evaluation history reads are
  deferred until those views are opened; Replay Guide reuses the selected trace. Local browser
  checks confirmed guide status, selected trace, one history request per requested workflow, and
  the intended endpoint counts.
- The blocking Google Fonts stylesheet measured 656 ms on a first local browser load (1,069 ms
  DOMContentLoaded; 1,756 ms loadEventEnd). A request-abort experiment reduced DOMContentLoaded to
  208 ms. After deferring the stylesheet while preserving its font families, an intentionally
  1,200 ms delayed-font experiment reached DOMContentLoaded in 335 ms and completed the session and
  overview requests (148 ms and 196 ms) before the font request completed. This proves local browser
  behavior only; no deployed network performance is inferred.
- One local fresh-process module import plus default SQLite app initialization measured 939 ms.
  This combines Python import and local schema initialization and is not a Vercel cold-start
  measurement. Code inspection shows the module-level app creates storage and connection once per
  worker initialization, not per ordinary request. Turso connection latency, serverless cold starts,
  function duration, and large remote datasets remain unverified.
- No new index or pagination was introduced: the existing event index was used, and current
  synthetic response sizes did not justify changing the session-list contract. No shared/global
  session cache was added.
- Private staging performance steps are documented in the README. They remain blocked until the
  previous database owner reviews possible DDL and a separate non-production Turso target is
  explicitly authorized. Do not reconnect to the previous database or claim deployed performance
  from local results.
- Final local regression after the optimization: `python -m pytest -q` passed 127 tests; Ruff
  check/format, JavaScript syntax validation, `git diff --check`, `python -m pip check`, and the
  project-scoped `pip_audit` all passed. A fresh local browser reload and synthetic session
  selection reported no console errors or failed requests. Remote Vercel/Turso behavior remains
  unverified.
