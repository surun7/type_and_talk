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
- **Tool Specs** (`tools/`): 14 tool definitions in OpenAI function-calling format, `ToolDispatcher`.
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

## User Flow (GUI Mode)

When the user runs ``tnt`` (no subcommand), the GUI shell activates:

1. User presses **Ctrl+Shift+Space** (default hotkey) → floating window fades in.
2. User types ``"Open Notepad and type Hello"`` + **Enter**.
3. ``AppController.run_task(text)`` → ``Planner.run(text, on_event=...)`` (asyncio).
4. Planner emits **StepStarted** → ``status_changed("Step 1")``.
5. Planner emits **LLMCalled** → status updates to "Step 1 — LLM responded".
6. Planner emits **ToolCallStarted("launch_app")** → status "Step 1 — launch_app" + dimmed line ``→ launch_app: {"app_name": "notepad.exe"}`` in response area.
7. Planner emits **ToolCallFinished(ok=true)** → status "Step 1 — ✓ launch_app — done".
8. (One or two more tool calls — ``wait_for_window``, ``type_text``.)
9. Planner emits **FinalAnswerReady("Done!")** → final message appended to response area, ``task_finished("success")`` fires.
10. Floating window hides per configured policy (default: ``on_success``). Tray icon returns to green (idle).

## Module Surface

Every public symbol re-exported from ``agent_uia`` (checked with ``pytest`` and import tests):

| Module | Public exports |
|---|---|
| ``agent_uia.main`` | ``app`` (typer), ``cli_main`` |
| ``agent_uia.planner`` | ``PlannerConfig``, ``TaskResult``, ``Planner``, ``PlannerEvent``, ``StepStarted``, ``LLMCalled``, ``ToolCallStarted``, ``ToolCallFinished``, ``FinalAnswerReady`` |
| ``agent_uia.executor`` | ``UIAWindowInfo``, ``UIAControlRef``, ``UIAControlNode``, ``UIAExecutor`` |
| ``agent_uia.tools`` | ``ToolDispatcher``, ``ALL_TOOL_SPECS``, ``ActionResult``, ``WindowRef``, ``ControlRef``, ``ScreenStateSummary``, ``_ToolSpec``, ``ALLOWED_KEYS``, ``14 spec classes``, ``_validate_launch_args``, serialization helpers |
| ``agent_uia.safety`` | ``SafetyVerdict``, ``SafetyDecision``, ``SafetyEvent``, ``SafetyConfig``, ``SafetyGate``, ``UnsupportedAppError``, ``LoginDetectedError``, ``default_gate``, ``assert_app_allowed``, ``assert_action_allowed`` |
| ``agent_uia.llm_client`` | ``LLMConfig``, ``LLMUsage``, ``LLMResponse``, ``LLMMessage``, ``SystemMessage``, ``UserMessage``, ``AssistantMessage``, ``ToolMessage``, ``ToolCall``, ``LLMClient``, ``LLMUnavailableError``, ``UsageLedger`` |
| ``agent_uia.ui`` | ``AppConfig``, ``AppController`` |
| ``agent_uia.ui.hotkey`` | ``GlobalHotkey``, ``parse_hotkey``, ``HotkeyError`` |
| ``agent_uia.ui.tray`` | ``State``, ``TrayIcon`` |
| ``agent_uia.ui.floating_window`` | ``FloatingWindow`` |
| ``agent_uia.ui.confirmation_dialog`` | ``ConfirmationDialog`` |

**Key design rules:**
- ``tool.py`` → ``ToolDispatcher.dispatch()`` always returns a plain ``dict`` (JSON-serializable).
- ``planner.py`` → ``Planner.run()`` is the single async entry point for task execution.
- ``safety.py`` → ``SafetyGate`` is a singleton; all executor paths call it.
- ``ui/`` → All Qt widgets assume ``QT_QPA_PLATFORM=offscreen`` for test environments.
- Every tool spec descends from ``_ToolSpec`` in ``tools/base.py``.

## Voice Pipeline

```
[User holds PTT hotkey]
    ↓
GlobalHotkey fires → AppController._on_ptt_press()
    ↓
AudioRecorder.start() (sounddevice RawInputStream)
    ↓
Each 30ms frame → silero-vad VADIterator (or RMS fallback) → SilenceDetector state machine
    ↓ (on silence timeout or max duration)
AudioRecorder.stop() → np.ndarray (buffer freed after use)
    ↓
SpeechRecognizer.transcribe(audio) (faster-whisper-base)
    ↓
[Chinese post-processing: dedupe hallucinations, normalize punctuation]
    ↓
TranscriptionResult.text → transcription_ready signal
    ↓
FloatingWindow fills input field → Enter → AppController.run_task(text)
    ↓
[Planner runs, emits events → FloatingWindow status + response area]
    ↓ (if TTS enabled)
SpeechSynthesizer.speak(final_answer) (edge-tts → MP3 → sounddevice playback)
```

### Model Lifecycle

```
NOT_INSTALLED ──▶ DOWNLOADING ──▶ READY
                      │
                      ▼
                   FAILED
```

- First run triggers download automatically; user can opt out.
- Models are cached under ``~/.cache/tnt/models/`` (or ``get_models_dir()``).
- Deletion transitions a model back to ``NOT_INSTALLED``.
- Failed downloads can be retried via ``tnt model-download <size>``.

## Skill System

```
[User clicks "Run" on a skill card]
    ↓
AppController.run_skill(skill_id, inputs)
    ↓
SkillRunner.run(skill, inputs)
    ↓
Topological sort of skill.steps (depends_on DAG)
    ↓
For each step:
  - tool step   → ToolDispatcher.dispatch(tool, args) → ToolResult
  - decision    → asteval(safe_eval) on context → jump to target step
  - complete    → return SUCCESS
    ↓
SkillResult → AppController → FloatingWindow status + history.jsonl
```

### Skill YAML Format

Skills are defined as YAML files with a ``steps`` array. Each step is one of
three kinds:

| Kind       | Purpose                                      |
|------------|----------------------------------------------|
| ``tool``   | Calls a registered tool (click, type_text…)  |
| ``decision`` | Evaluates a sandboxed expression to branch |
| ``complete`` | Marks the end of a success path           |

Steps declare ``depends_on`` dependencies. The runner topologically sorts
them and executes in dependency order. A step whose dependencies are not
met (or whose path was not reached by a decision) is skipped.

### Security

- Decision expressions are evaluated in an ``asteval.Interpreter`` with all
  dangerous builtins (``__import__``, ``eval``, ``exec``, ``open``) blocked.
- Tool dispatch goes through the same ``ToolDispatcher`` and safety gate
  used by the LLM planner.
- Skill YAML files cannot execute arbitrary code — only invoke documented
  tool functions.

### Module Surface

| Module                             | Public exports |
|------------------------------------|----------------|
| ``agent_uia.skills.schema``        | ``Skill``, ``SkillStep``, ``SkillInput``, ``ToolStep``, ``DecisionStep``, ``CompleteStep``, ``SkillErrorPolicy``, ``SkillStepType`` |
| ``agent_uia.skills.parser``        | ``SkillParseError``, ``parse_skill_file``, ``parse_skill_yaml``, ``validate_skill_graph`` |
| ``agent_uia.skills.context``       | ``SkillContext``, ``SkillContextError`` |
| ``agent_uia.skills.runner``        | ``SkillRunner``, ``SkillResult``, ``SkillStepRecord``, ``SkillStatus`` |
| ``agent_uia.skills.loader``        | ``LoadedSkill``, ``SkillRegistry``, ``SkillSource``, ``default_registry`` |
| ``agent_uia.skills`` (re-export)   | All of the above |

## Performance

### Data Flow

```
User action → instrumented component → in-memory ring buffer
                                            │
                                    every 30 s (flush interval)
                                            │
                                            ▼
                                    logs/perf.jsonl
                                            │
                                     ┌──────┴──────┐
                                     ▼              ▼
                              Performance tab   tnt perf CLI
                              (live charts)     (phase timing)
```

Every instrumented component (planner, executor, LLM client, hotkey handler)
records ``MetricPoint`` objects into a shared ``PerformanceMonitor`` singleton.
Points are held in a fixed-size ring buffer (default 10 000 entries). A
background asyncio task flushes the buffer to ``logs/perf.jsonl`` every
30 seconds (configurable via ``perf.flush_interval_s``). The JSONL file is
append-only and rotated by loguru.

The Performance tab in the GUI reads both the in-memory ring buffer (for
live sub-second data) and the JSONL file (for historical 5-minute rolling
charts). The CLI command ``tnt perf`` reads the JSONL file directly and
prints aggregate statistics for a task.

### Cold Start Sequence

Cold start is the time from ``tnt`` (or GUI launch) to the app being ready
for user input. The sequence is split into two tracks:

**Critical path** (blocks readiness, must complete in ≤ 1.5 s):

```
tnt (or GUI entry)
  │
  ├─ 1. Platform check (assert_windows)
  ├─ 2. Logging setup (loguru)
  ├─ 3. Safety gate init (default_gate)
  ├─ 4. Config load (ConfigStore.load)
  ├─ 5. Tray icon creation
  ├─ 6. Hotkey registration (GlobalHotkey)
  └─ 7. Event loop enter → ready for input
```

**Background init** (does NOT block readiness, may complete after 1.5 s):

```
  ├─ 8. Model manager init (lazy, deferred until first voice use)
  ├─ 9. Window pre-warming (create Qt widgets hidden → fast show later)
  ├─10. Performance monitor init (default_monitor)
  ├─11. Cache creation (ControlTreeCache, LLMResponseCache)
  └─12. Periodic flush task start (every 30 s)
```

Steps 8–12 are kicked off via ``asyncio.create_task`` or lazy initialisation
and do not delay the tray icon from appearing or the hotkey from being
responsive.
