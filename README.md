# ⚡ CS26048-AgentReplay

> **A logging proxy, observability timeline, and deterministic replay engine for AI agent tool and model calls.**

Developed as the practical implementation of **Project Proposal (24CS061)**.

## Project Documents

- [Problem Statement](docs/Problem-Statement.md)
- [Literature Survey](docs/Literature-Survey.md)
- [Project Timeline](docs/Project-Timeline.md)
- [Requirements](docs/Requirements.md)
- [Project Proposal](docs/PROPOSAL.md)
- [Architecture and implementation decisions](docs/DECISIONS.md)

---

## 🎯 The Problem

When conventional software fails, developers can attach debuggers, inspect stack traces, and step through execution lines. But in autonomous AI agents, the execution path is generated at runtime by stochastic LLMs and disappears after the request finishes. 

When an agent loops on a tool, quiet-fails after a malformed payload, or hallucinates an unexpected parameter, reproducing the issue is notoriously unreliable. Re-running the agent incurs network delays and API billing, and often takes an entirely different path.

`agent-replay` solves this gap:
1. **Records** every tool call and model call with timestamps, parameters, return values, token usage, and calculated cost.
2. **Reconstructs** sessions as an interactive, chronologically ordered visual timeline.
3. **Replays** past sessions **stochastically-free and with $0 API cost** by serving stored responses from SQLite.
4. **Forks** executions by substituting a recorded response at step $k$, allowing developers to observe how downstream model calls adapt to modified states.
5. **Detects** statistical irregularities (loops, cost spikes, runaway durations) with transparent, explainable rule-based detectors.

---

## 🏗️ Architecture

```mermaid
graph TD
    Agent[AI Agent: LangGraph / Google ADK] -->|Model & Tool Invocations| Proxy[Recorder & Interceptor Proxy]
    Proxy -->|Monotonic Event Sequence| DB[(SQLite Database)]
    Proxy -->|Look up Model Rates| Prices[prices.json]
    DB -->|Read Sessions & Events| API[FastAPI Backend]
    API -->|Serve Static HTML/JS UI| UI[Interactive Timeline Web UI]
    DB -->|Fetch Trace| Replay[Replay Engine: Strict / Forked]
    Replay -->|Serve Cached Responses / Halt on Divergence| Agent
    DB -->|Scan Sessions| Detector[Rule-Based Anomaly Detector]
    Detector -->|Attach Flags & Culprit IDs| UI
```

Model-call replay is implemented and validated for explicit model wrappers (the ADK-style loop). For LangGraph, model calls are recorded for audit/cost tracking but the live model is still called during replay; LangGraph model-call substitution is a known limitation, listed in Future Work.

---

## 📊 Core Data Schema

All interactions are captured in SQLite under the `events` table:

| Field | Type | Description |
| :--- | :--- | :--- |
| `session_id` | TEXT | Unique identifier grouping session events |
| `seq` | INTEGER | Monotonically increasing execution counter (1, 2, 3...) |
| `type` | TEXT | Event classification: `'tool_call'` or `'model_call'` |
| `name` | TEXT | Identifier (e.g. `search_docs`, `gemini-1.5-flash`) |
| `args_json` | TEXT | Full JSON serialized inputs / prompts |
| `result_json` | TEXT | Full JSON serialized outputs (NULL on failure) |
| `error` | TEXT | Traceback / error message if call failed |
| `started_at` | TEXT | UTC ISO-8601 timestamp |
| `duration_ms` | REAL | High-precision execution duration in milliseconds |
| `tokens_in` | INTEGER | Input / prompt token count |
| `tokens_out` | INTEGER | Output / candidate token count |
| `cost_usd` | REAL | Calculated cost when pricing and usage are known |
| `provider`, `model` | TEXT | Provider and resolved model, when available |
| `tokens_total`, `cached_tokens` | INTEGER | Usage totals and cached-token metadata, when reported |
| `cost_status` | TEXT | `actual`, `estimated`, or `unavailable` |

---

## 🚀 Quickstart

### 1. Prerequisites
- Python 3.11+ (Python 3.12 recommended)
- Git

### 2. Environment Setup
Clone the repository and activate the virtual environment:
```powershell
cd D:\agent-replay
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Provider-backed Playground calls are optional. Set only the provider key(s) you intend to use in
`.env`; keys are read server-side and are never stored in sessions or sent to the browser:
```env
GEMINI_API_KEY=AIzaSy...
DEFAULT_MODEL=gemini-2.0-flash
# OPENAI_API_KEY=
# ANTHROPIC_API_KEY=
```

The dashboard remains useful without any provider key: local recording, strict replay,
counterfactual experiments, timeline inspection, and analytics do not make paid network calls.
The AI Playground calls a provider only after the user submits a prompt. Provider responses and
prompts are recorded in a dedicated Playground session for debugging, so do not submit secrets or
personal data. Usage and cost displays label unavailable pricing instead of treating it as zero.

Configure or customize token prices in `prices.json`:
```json
{
  "models": {
    "gemini-1.5-flash": {
      "input_cost_per_million": 0.075,
      "output_cost_per_million": 0.30
    }
  }
}
```

---

## 🎬 Running the Failure Scenarios & Replay Demos

### Scenario 1: Tool Looping & Rule-Based Detection
Run an agent stuck in a loop querying documentation with identical arguments:
```powershell
python scenarios/scenario_1_loop.py
```
**Outcome**:
- The session is recorded into SQLite.
- The `RepeatedToolCallsRule` flags the session with severity **DANGER**.
- Sequence IDs of the culprit loop steps are tagged and highlighted in the UI.

### Scenario 2: Strict Replay & Forked Substitution Recovery
Run an end-to-end failure, strict reproduction, and recovery test:
```powershell
python scenarios/scenario_2_malformed_response.py
```
**Outcome**:
1. **Baseline Failure**: The deterministic account tool returns an error payload and the workflow halts; the failed response is persisted in the timeline.
2. **Strict Runtime Replay**: Runs the decorated workflow against stored responses without invoking the underlying tool.
3. **Forked Runtime Execution**: Substitutes sequence #1 with valid account data (`{"status": "ok", "balance": 500.0}`), then executes the real downstream `calculate_credit` tool and persists a separate fork session.

To compare an existing supported baseline in the UI, open **Experiments**, select a recorded
scenario-2 account-workflow session, choose its first tool-call substitution, and submit a JSON
replacement response. The comparison stores its baseline/fork relationship and complete result so
it can be reopened after navigating away or reloading. The fork uses the existing deterministic
replay context, substitutes the first `query_user_account` result, and executes the supported
downstream workflow; it does not run arbitrary recorded agent graphs. The comparison identifies
the recorded baseline, strict replay reconstruction, fork outcome, substituted event, and event
diff. Recorded per-event durations are not a performance benchmark.

`POST /api/replay` remains trace validation only; it does not re-execute an agent workflow.
Guided experiment endpoints are `GET /api/experiments/baselines`, `POST /api/experiments`,
`GET /api/experiments`, and `GET /api/experiments/{experiment_id}`. The older
`POST /api/experiments/counterfactual` endpoint remains available for compatibility.

### Deterministic evaluation

Recorded session outputs and saved guided comparisons can be evaluated offline. The evaluator
reads the final recorded event result and supports JSON expected values, required dotted-path
fields, required phrases, recorded error acceptance, and optional maxima for summed event
duration, recorded tokens, and estimated cost. Criteria are validated by the server; arbitrary
user code and paid model judges are not executed.

```json
{
  "expected_output": {"credit_limit": 1250.0},
  "required_fields": ["credit_limit"],
  "required_phrases": [],
  "allow_tool_errors": false,
  "max_latency_ms": 5000,
  "max_tokens": 2000,
  "max_cost_usd": 0.02
}
```

Use `POST /api/evaluations/sessions/{session_id}` to evaluate a recorded session or
`POST /api/experiments/{experiment_id}/evaluations` to evaluate the persisted baseline and fork
with identical criteria. `GET /api/evaluations?session_id=...` and
`GET /api/experiments/{experiment_id}/evaluations` return append-only evaluation history.
Evaluator outputs include status explanations and event references. Expected-value checks inspect
the final recorded result (nested object criteria are subset matches); required fields use dotted
paths and required phrases are case-insensitive string matches. Missing evidence is reported as
unavailable, not as a pass.
Session evaluation may include an optional `replay_calls` array (each call has `type`, `name`, and
`args`) to persist strict-match, divergence, or incomplete-sequence evidence against the trace.

Replay validity remains separate from output quality. Session evaluations do not run strict replay;
saved experiment evaluations report the replay result recorded by the guided experiment. Efficiency
measurements do not score answer quality: summed event durations are not wall-clock benchmarks,
and configured-rate costs are estimates, not provider-confirmed billing. No weighted aggregate
score is calculated.

---

## 🌐 Interactive Timeline Web UI

Launch the FastAPI observability dashboard:
```powershell
uvicorn agent_replay.api:app --reload --host 127.0.0.1 --port 8000
```
Open your browser to: **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

### Features:
- **Session Explorer**: Browse past sessions with start time, duration, and cost availability.
- **Metric Cards**: Aggregate tokens, costs, durations, and tool vs model call ratios.
- **Flagged Badges**: Warning and Danger alert banners for anomaly sessions.
- **Chronological Timeline**: Step-by-step visual cards with duration badges, cost pills, and collapsible JSON payloads for both inputs and outputs.
- **Culprit Highlighting**: Cards identified by anomaly rules glow with red borders and `[FLAGGED]` pills.
- **Guided Experiments**: Compare eligible recorded account-workflow baselines with persisted,
  deterministic forks. Strict replay, substituted output, and downstream fork execution are
  labeled separately. Other recorded agent workflows are not currently eligible.
- **Deterministic Evaluation**: Configure expected JSON values, required output fields/phrases,
  error acceptance, and optional resource thresholds; inspect evidence-backed session and
  baseline/fork results offline with append-only history.
- **Model Usage & Costs**: Filter recorded model usage by provider, model, and execution session.
  Per-session records avoid conflating a baseline with its fork. Configured-rate values are
  estimates, not provider-confirmed bills; missing usage or pricing remains unavailable.
- **AI Playground**: Exercise configured OpenAI, Anthropic, or Gemini adapters from the server,
  with each submitted run recorded as its own session and failed provider calls recorded as failed
  events. Provider keys stay server-side. Recorded session outputs can also be evaluated without
  making a provider call.
- **Live Monitor / Run**: Refresh the configured server's recorded-session list periodically.
  This is not a stream of per-event state and does not imply that an agent is currently running.
  Scenario execution remains disabled unless `LIVE_RUN_ENABLED` is explicitly enabled.
- **Navigation**: A collapsible sidebar selects one workspace view at a time; the selected session
  remains available as shared context and the session list is shown on Traces.

## ☁️ Vercel Deployment

The project includes a Vercel ASGI entrypoint in `api/index.py` and uses Turso for persistent serverless storage. Create a Turso database, then configure these Vercel environment variables for Production, Preview, and Development:

```text
TURSO_DATABASE_URL
TURSO_AUTH_TOKEN
GEMINI_API_KEY
DEFAULT_MODEL
USD_TO_INR
LIVE_RUN_ENABLED
CONFIG_MUTATIONS_ENABLED
```

Import `Deep1067/CS26048-AgentReplay` into Vercel with the repository root as the project directory. The first application startup creates the required sessions, events, and settings tables automatically. Pricing and detector settings are stored in the database when Turso is configured; local development continues to use SQLite and local configuration files.

`LIVE_RUN_ENABLED` and `CONFIG_MUTATIONS_ENABLED` default to `false`. Set them to `true` only in a
trusted local environment; the application does not use a browser-visible shared secret for
authorization. The built-in monitor can still refresh recorded sessions and instrumented
integrations can still record into the configured storage when scenario execution is disabled.
Scenario execution remains limited to server-defined, step-capped workflows; this switch does not
enable arbitrary task execution.

---

## 🧪 Running Automated Tests

Run the full unit and integration test suite:
```powershell
$env:PYTHONPATH = "src"
pytest -v
```

Run code formatting and linting:
```powershell
ruff check .
ruff format --check .
```
