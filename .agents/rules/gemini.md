---
trigger: always_on
---

You are helping a 3rd-year CS student build "agent-replay", a record-and-replay
debugging tool for AI agent tool calls. Read docs/PROPOSAL.md before any work.

- Stack: Python 3.12, FastAPI, sqlite3 (no ORM), plain HTML/JS for UI (no build step), pytest, ruff.
- The core recorder must be framework-agnostic; LangGraph/ADK code lives only in adapters/.
- Never hardcode secrets. Read GEMINI_API_KEY from .env. Never commit .env or *.db.
- Work one milestone at a time. Before coding, write a short plan and WAIT for my approval.
- Keep code simple and readable. The student must be able to explain every file in a viva.
  Prefer small functions and comments explaining WHY, not what.
- Every milestone ends with passing tests and a short entry in docs/DECISIONS.md.
- Do not add features outside the proposal scope (no multi-agent, no ML detection,
  no root-cause diagnosis, no injection detection).
- If replay diverges from the recording, halt and report the divergence. Never fabricate a response.