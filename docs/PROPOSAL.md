# **Project Proposal** 

Name: Deep Patel  |  ID: 24CS061 

_Revised Draft_ 

## **Problem Definition Statement** 

AI agents are increasingly used to automate tasks by autonomously deciding which external tools to call — searching documents, querying databases, invoking APIs, or running code. A single user request may trigger several tool calls in sequence, where each result influences what the agent does next. 

Unlike traditional programs, where the execution path is written down in code and can be stepped through, an agent’s execution path is produced by the model at runtime and is not recorded anywhere by default. When an agent produces a wrong answer, loops on the same tool, or quietly fails after a malformed response, the developer has no structured record of what was attempted or in what order. Debugging today means adding logging by hand to each tool, or re-running the agent and hoping the failure repeats — which it often does not, because the model may take a different path each time. API cost has the same blind spot: a developer can see the monthly bill, but not which session or which tool call caused it. 

This project addresses that gap for single-agent tool-calling workflows. It proposes a lightweight system that records every tool call an agent makes along with its cost, lets the developer reconstruct the session afterwards as an ordered timeline, and — the central idea of this revision — replays the recorded session against the agent so the same execution can be reproduced on demand without calling the real tools again. 

## **1. Product Overview** 

### **1.1 Users** 

1. AI agent developer / small development team — builds tool-using AI workflows and needs to see what the agent actually did when behaviour is unexpected. 

2. Engineering / team lead — needs to attribute API cost to specific sessions and features rather than reading a single monthly total. 

### **1.2 Functionality** 

The system sits between an AI agent and the tools it calls. Every call is intercepted and recorded: which tool was invoked, the arguments passed to it, the result returned, how long it took, and the token cost associated with it. Records are stored in order and grouped by session. 

A web interface lets the developer open any past session and read the sequence of calls that led to the final outcome. Because the tool responses are stored, the same session can also be replayed: the agent is run again, but instead of the real tools being called, the previously recorded responses are returned. This makes a failure reproducible on demand, removes network and API cost from the debugging loop, and allows the developer to change one recorded response and observe whether the failure still occurs. 

A small rule-based detector flags sessions worth looking at, such as a tool being called repeatedly or a session costing far more than the norm. 

### **1.3 Features** 

- Session-level recording of every agent tool call — tool name, input arguments, returned output, duration 

- Per-call and per-session cost tracking derived from token usage 

- Timeline view showing the ordered sequence of calls within a session 

- Deterministic replay of a recorded session using stored tool responses instead of live tool calls 

- Response substitution during replay — altering one recorded tool response to test its effect on the outcome 

- Rule-based flags for repeated/looping calls, unusually high-cost sessions, and unusually long sessions 

## **2. Proposed Solution** 

Build a logging proxy that intercepts tool calls made by an AI agent and writes each one to a local database, capturing input, output, duration, and API cost. On top of this, build a web-based timeline interface for reconstructing a session, and a replay mode that re-runs a recorded session by serving stored responses in place of live tool calls. 

Record-and-replay debugging is a long-established technique in conventional software. The contribution of this project is applying it to agent tool calls, where non-determinism makes failures unusually hard to reproduce. Replay is what distinguishes this system from a logging dashboard: the recorded session becomes an executable artifact rather than a document to read. 

Version 1 is scoped to a single agent integrating with two or three tools. To avoid demonstrating the system only against an agent built for the purpose, it will be validated against at least two agents built on existing, off-theshelf frameworks, so the recorded failures are observed rather than manufactured. Multi-agent support and machine-learning-based anomaly detection remain future extensions and are not part of the committed V1 scope. 

## **3. Expected Outcome & Future Plan** 

### **3.1 Expected Outcome** 

A working, demonstrable tool that records an AI agent’s tool-call activity together with its cost, displays the session as an ordered timeline, and replays a recorded session deterministically without re-invoking the real tools. It will flag a small number of rule-based anomalies, be validated against at least two agents not written for this project, and be documented with a README and a short demo as an open-source project. 

A successful demonstration is: an agent fails during a live run; the developer opens the recorded session, reads the sequence of calls that preceded the failure, replays the session to reproduce it without further API cost, substitutes one tool response, and observes whether the failure persists. 

### **3.2 Future Plan** 

- Extending observation to multiple agents working together 

- Using the recorded traces as a dataset for machine-learning-based anomaly and drift detection, replacing fixed rules 

- Building a regression suite from saved failing sessions, so past failures can be re-checked after a prompt or code change 

- Cross-provider cost comparison 

## **4. Challenges** 

- **Unfamiliar domain.** Agent tool-calling is new to me; addressed with a dedicated learning phase before core development, and by building the interception layer first so the least-understood component is proven earliest. 

- **Replay fidelity.** During replay the agent may request a call that was never recorded, since the model can take a different path. V1 will handle this by halting replay and reporting the divergence rather than fabricating a response — an explicit and documented limitation. 

- **Scope against available time.** Limited weekly hours alongside coursework and placement preparation; addressed by limiting V1 to a single agent and rule-based detection, and by sequencing the build so an incomplete semester still yields a working subset. 

- **Useful rules without a model.** Designing rule-based detection that is simple but still meaningfully useful, without an ML model in V1. 

## **5. Scope Boundaries** 

The following are deliberately excluded from V1 and are stated here to make the boundary of the work explicit: 

- The system does not diagnose why a failure occurred. It records and reproduces evidence; the developer draws the conclusion. 

- The system does not attempt to detect adversarial manipulation or prompt injection. Rule-based detection identifies statistical irregularities such as loops and cost spikes, not malicious intent. 

- The system observes one agent at a time and does not trace interactions between multiple agents. 

## **6. References** 

1. OWASP Top 10 for LLM Applications (2025) — motivation for visibility into autonomous agent actions. 

2. Provider documentation for LLM function/tool calling (OpenAI / Anthropic API docs). 

3. Record-and-replay debugging literature in conventional software systems (e.g. deterministic replay debuggers such as rr). 

