# Architecture

## Pipeline (current state)

```
                          ┌───────────────────────────────────────┐
                          │            SAFETY GATE               │
                          │  (singleton, immutable, first-call)  │
                          │                                       │
   User Input ──────────▶ │  check_app() ──▶ ALLOW / BLOCK /      │
   (CLI: tnt run)         │                  REQUIRE_CONFIRMATION  │
                          │                                       │
                          │  check_action() ──▶ ALLOW /            │
                          │                     REQUIRE_CONFIRMATION│
                          └──────────────┬────────────────────────┘
                                         │
                          ┌──────────────▼────────────────────────┐
                          │         LLM PLANNER                   │
                          │  (IMPLEMENTED — Prompt 2)             │
                          │                                       │
                          │  ┌──────────────────────────┐         │
                          │  │ ReAct Loop:              │         │
                          │  │  1. System prompt        │         │
                          │  │  2. Call LLM (DeepSeek)  │         │
                          │  │  3. Parse tool calls     │         │
                          │  │  4. Dispatch to executor │         │
                          │  │  5. Append tool results  │         │
                          │  │  6. Repeat until final   │         │
                          │  │     answer or guard hit  │         │
                          │  └──────────────────────────┘         │
                          │                                       │
                          │  Guards:                              │
                          │  • max_steps = 20                     │
                          │  • max_cost = $0.10/task              │
                          │  • BLOCK propagation to user          │
                          │  • planner_timeout_s = 120s           │
                          └──────────────┬────────────────────────┘
                                         │
                          ┌──────────────▼────────────────────────┐
                          │        TOOL DISPATCHER                │
                          │  (IMPLEMENTED — Prompt 2)             │
                          │                                       │
                          │  14 tool specs:                       │
                          │  launch_app, find_window,             │
                          │  list_windows, get_control_tree,      │
                          │  click, type_text, set_value,         │
                          │  invoke, press_key, wait_for_window,  │
                          │  wait_for_control, close_window,      │
                          │  read_screen_state,                   │
                          │  request_user_confirmation            │
                          │                                       │
                          │  Window/control ID registries         │
                          │  safety gate integration              │
                          └──────────────┬────────────────────────┘
                                         │
                          ┌──────────────▼────────────────────────┐
                          │        UIA EXECUTOR                   │
                          │  (IMPLEMENTED — Prompt 1)             │
                          │                                       │
                          │  Wraps uiautomation.                  │
                          │  No raw handles leak to callers.      │
                          │  Every method calls safety gate       │
                          │  BEFORE any UIA operation.            │
                          └──────────────┬────────────────────────┘
                                         │
                          ┌──────────────▼────────────────────────┐
                          │          AUDIT + USAGE LOGS           │
                          │                                       │
                          │  ./logs/audit.log  — JSON lines       │
                          │  ./logs/usage.jsonl — JSON lines      │
                          │  ./logs/agent-uia.log — loguru        │
                          │                                       │
                          │  Both append-only by design.          │
                          └───────────────────────────────────────┘
```

## What is implemented (Prompts 1 + 2)

- **Platform check** (`platform_check.py`): Hard Windows guard.
- **Logging setup** (`logging_setup.py`): loguru + sensitive-field redaction.
- **Safety gate** (`safety.py`): Blocklist, login detection, action confirmation, audit log.
- **UIA Executor** (`executor.py`): Clean `uiautomation` wrapper, opaque references.
- **LLM Client** (`llm_client.py`): DeepSeek-compatible async client, retry, `UsageLedger`.
- **Tool Specs** (`tools.py`): 14 tool definitions in OpenAI function-calling format, `ToolDispatcher`.
- **Planner** (`planner.py`): ReAct loop with guards, event callbacks.
- **System Prompt** (`prompts/system_prompt.md`): Identity, 9 hard rules, capabilities.
- **CLI** (`main.py`): `tnt run`, `tnt chat` (stub), `tnt demo`, `tnt doctor`.
- **Demo** (`demo.py`): `--no-llm` (UIA smoke test) and `--llm` (full planner path).

## What is NOT yet implemented (Prompt 3)

- Interactive REPL (`tnt chat`)
- Streaming UX with real-time token display
- Input layer (ASR, structured JSON API)
- Packaging / MSI installer
- CI/CD pipeline

## Design: Safety Gate as Immutable Frontline

The safety gate is a **lazy singleton** — initialized once on first `default_gate()`
call. The design is intentionally restrictive:

1. **No execution path bypasses it.** `ToolDispatcher.dispatch()` catches
   `UnsupportedAppError` and `LoginDetectedError` from the safety gate and
   returns them as structured `{ok: false, error: "BLOCKED: ..."}` results.
   The planner propagates these to the LLM, which the system prompt instructs
   to abort and tell the user.

2. **The gate cannot be reconfigured at runtime.** `SafetyConfig` is frozen
   (pydantic `model_config = {"frozen": True}`).

3. **The blocklist is non-empty by default.** 35+ entries. User can add but
   not start empty.

4. **Login screens are always blocked** for recognized interactive apps.

5. **The LLM is treated as untrusted input.** All tool calls go through the
   safety gate. The system prompt is shipped as a file users can review.
