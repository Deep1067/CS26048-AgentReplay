# Checkpoint log — agent-replay

This file is the handoff record if a session quota is hit. Newest entries are at the bottom.

## Project status (as of 2026-10-02)

Milestones **M0–M6 are implemented** in git (`559836e` … `b241571`): recorder, SQLite, pricing, FastAPI timeline UI, strict/forked replay, rule-based detector, LangGraph + Google GenAI agents, two failure scenarios, README.

**Not in scope yet:** Vercel/Turso production deploy. Storage is still local SQLite (`agent_replay.db`).

## What works without a Gemini call

| Command | What you see |
| :--- | :--- |
| `pytest` with `PYTHONPATH=src` | Full unit/integration suite |
| `python scenarios/scenario_1_loop.py` | Repeated-tool detector flags |
| `python scenarios/scenario_2_malformed_response.py` | Strict replay + forked recovery (no live LLM) |
| `uvicorn agent_replay.api:app --reload --host 127.0.0.1 --port 8000` | Timeline UI at http://127.0.0.1:8000 |

## Live Gemini demo

```powershell
cd D:\agent-replay
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
$env:PYTHONUTF8 = "1"
python run_live_demo.py
```

Then open the UI and select the printed `Session ID`.

`.env` must contain `GEMINI_API_KEY`. Do not commit `.env`.

Default model is `gemini-flash-lite-latest` because `gemini-3.8-flash` returned **503 high demand** on 2026-10-02. Override with `DEFAULT_MODEL` in `.env` if needed.

## Architecture (short)

Agent tools and model calls go through interceptors → SQLite `events` table (`session_id`, monotonic `seq`) → FastAPI `/api/sessions` + static timeline. Replay engine serves recorded results (strict) or substitutes at step `k` then goes live (forked).

## Cursor session 2026-10-02

### Context

Antigravity had finished M0–M6, then the live demo failed: deprecated models, SQLite thread errors, then `UNIQUE (session_id, seq)` when LangGraph ran tools in parallel. Quota ended that session.

### Done in this environment

1. Audited the repo against `docs/PROPOSAL.md` and the milestone plan.
2. Made SQLite storage use **one shared connection** plus a **thread lock** so parallel tool threads get unique `seq` values.
3. Wired `@record_tool` and the LangChain model callback into `src/agents/langgraph_agent.py` without stacking `@record_tool` on `@tool` (that breaks LangChain schema introspection).
4. Added `tests/test_recorder.py::test_concurrent_seq_allocation` and a LangGraph recording unit test.
5. Made scenario 2 **idempotent** (`delete_session` before re-run) so leftover file-DB rows do not fail UNIQUE.
6. Rewrote `run_live_demo.py` (UTF-8, unique session id, no emoji, no stacked decorators).
7. Updated `prices.json` for Gemini 3.8 family; default model now `gemini-flash-lite-latest`.
8. **Live demo succeeded:** session `live_demo_20261002_151216`, 9 events (5 tools, 4 model calls), Alice order total **$249**, refund policy cited. Cost about `$0.000237`.
9. pytest: **37 passed**.

### Still remaining (optional)

- Vercel + Turso (libSQL) for a free hosted demo.
- Recorded model-call replay for LangGraph (strict replay today is proven on decorated tools / `record_model_call`, not a full LangGraph graph replay).
- `create_react_agent` deprecation warning (LangGraph v1 → `langchain.agents.create_agent`).
- README still mentions older Gemini 1.5 examples in places.

### Resume commands

```powershell
$env:PYTHONPATH = "src"
pytest -q
python run_live_demo.py
uvicorn agent_replay.api:app --reload --host 127.0.0.1 --port 8000
```
