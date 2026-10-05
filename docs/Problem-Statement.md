# Problem Statement

AI agents generate execution paths dynamically through model decisions and tool calls. When an agent loops, sends malformed input, or fails after an external call, the original sequence is difficult to inspect and reproduce. Re-running the agent may choose a different path and can incur additional API and tool costs.

This project addresses the problem with a lightweight observability and deterministic replay system for single-agent, tool-calling workflows. It records model and tool inputs, outputs, execution order, duration, token usage, estimated cost, and failures by session. A timeline UI makes the recorded behavior inspectable, while strict replay serves stored responses and stops on divergence instead of fabricating missing responses. Forked replay supports controlled tool-response substitution for hypothesis testing.

The initial scope is limited to single-agent workflows using two or three tools, including LangGraph and Google GenAI/ADK-style integrations. Multi-agent tracing, ML-based anomaly detection, and automated root-cause diagnosis are outside the current scope.
