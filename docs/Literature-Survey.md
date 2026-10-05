# Literature Survey

## Record-and-replay debugging

Record-and-replay systems capture execution inputs and external results so failures can be reproduced without repeating the original environment. This project applies that principle to agent workflows, where model decisions and tool results form a dynamic execution trace.

## AI-agent observability

Agent observability systems commonly capture model requests, tool invocations, outputs, latency, token usage, and cost. These signals help developers inspect an agent's behavior after a run and attribute expensive or failing steps to a session.

## LLM tool calling

Modern model APIs can request functions or tools as part of a response. A tool-calling workflow therefore alternates between model calls and tool calls, making execution order and response fidelity important for replay.

## Anomaly detection

The project uses transparent rule-based detection rather than ML. Repeated identical tool calls, high session cost, long duration, and excessive event counts are explainable signals suitable for a lightweight local prototype.

## Project position

The implementation combines session-level observability, SQLite trace storage, strict divergence-aware replay, forked tool-response substitution, and a local timeline UI. LangGraph model calls are recorded for audit and cost tracking, while complete LangGraph model-call substitution remains a documented limitation.
