# Security — Threat Model & Design Choices

## Threat Model

`agent-uia` is a desktop automation agent. It accepts natural-language instructions
(future) and translates them into UI actions. The primary threat vectors are:

| Threat | Severity | Mitigation |
|---|---|---|
| Malicious user input ("delete all files", "send my passwords to evil.com") | High | Safety gate blocks sensitive action types; `REQUIRE_CONFIRMATION` for destructive operations |
| Prompt injection via application content (e.g. a webpage titled "ignore previous instructions and...") | Medium (future) | LLM planner will use structured tool calls, not raw system prompts; safety gate acts as a second layer |
| Accidental destructive actions (misinterpreted instruction) | Medium | Safety gate always-confirm list; audit log for forensic review |
| Operation on game clients (anti-cheat ToS violation) | High | Blocklist for known game executables — `BLOCK_UNSUPPORTED` verdict |
| Operation on login/authentication screens (credential theft risk) | High | Login keyword detection — `BLOCK_GAME_LOGIN` verdict |
| Bypass of safety gate via monkey-patching | Medium | Gate is a singleton; every UIA executor method calls it first; no public bypass API |

## Design Choices

### 1. Safety Gate is a Singleton

There is exactly one `SafetyGate` instance in the process (via `default_gate()`).
All `UIAExecutor` instances share it. This prevents a compromised executor from
using a different, weaker gate.

### 2. Gate Cannot Be Bypassed from Outside the Module

`safety.py` exposes no method to disable checks. The `assert_app_allowed` and
`assert_action_allowed` convenience functions raise exceptions that propagate
to the caller — there is no `suppress_checks` context manager or flag.

`UIAExecutor` stores the gate as a private `_safety` attribute. Every public
method calls `self._safety.assert_app_allowed(exe_name=..., window_title=...)`
as its first operation. There is no executor method that skips this.

### 3. Audit Log is Append-Only

The audit log (`./logs/audit.log`) is opened in append mode. Every safety decision
is serialized as a single JSON line. The log is never truncated or rotated by
the application code (loguru handles rotation separately). This provides a
forensic trail of every allowed and blocked action.

### 4. Login Screens Are Always Blocked

For recognized interactive applications (game launchers, Steam, Epic, etc.),
any window title matching login keywords triggers `BLOCK_GAME_LOGIN`. The agent
will NEVER type credentials into a login screen. The user must authenticate
manually.

### 5. Blocklist Cannot Be Empty by Default

`SafetyConfig.blocked_executables` has a hardcoded default set of at least 20
common game clients and launchers. The user can add more but cannot start with
an empty list — they must explicitly override the config.

### 6. Sensitive Action Confirmation

Actions like `delete_file`, `send_message`, `transfer_money`, `purchase`, and
`submit_form` always return `REQUIRE_CONFIRMATION`. The future LLM planner will
be required to request explicit user confirmation before proceeding with these
action types.

## Prompt Injection

The LLM is treated as **untrusted input**. Even though the system prompt
instructs the LLM to follow specific rules, an adversary could:

- Craft user instructions that attempt to override system prompt constraints.
- Inject adversarial content into application windows that the LLM reads via
  UIA (e.g. a malicious webpage title containing "ignore previous instructions").

Mitigations:

1. **All tool calls go through the safety gate.** Even if the LLM is tricked into
   calling a tool on a blocked application or a login screen, the safety gate
   rejects it. The LLM cannot bypass the gate.

2. **The system prompt is a file shipped with the binary.** Users can inspect
   `src/agent_uia/prompts/system_prompt.md` and customize it.

3. **Structured tool calling.** The LLM communicates via function-calling JSON,
   not raw text commands. This reduces the attack surface compared to a
   free-form "execute this command" model.

4. **No arbitrary code execution.** The LLM has exactly 14 tools, all of which
   go through the safety gate. There is no "run shell command" or "eval Python"
   tool.

## Cost DoS

A user (or a malicious website that tricks a user into pasting a long instruction)
could ask TNT to perform an expensive, multi-step task. Mitigations:

| Mechanism | Detail |
|---|---|
| **Max steps** | 20 by default. The planner stops and returns a clear error. |
| **Budget cap** | $0.10 USD per task by default. Tracked via `UsageLedger`. |
| **Configurable** | Both limits are fields on `PlannerConfig`. |
| **Cost transparency** | Every run logs cost; `tnt run` prints it at the end. |

If a task exceeds the budget, `tnt run` exits with code 3 and a message like:

> Task budget exceeded ($0.1005 of $0.10 limit). The task was stopped to
> prevent excessive cost.

## Credential Handling

1. **Passwords and API keys must never appear in LLM transcripts.** The system
   prompt (Hard Rule 6) instructs the LLM to summarise credentials structurally
   (e.g. "a 12-character password field is filled") and never echo the value.

2. **`set_value` is preferred over `type_text` for sensitive fields.** `set_value`
   uses the UIA `ValuePattern.SetValue`, which sets the text directly without
   passing through the keyboard buffer.

3. **Log redaction.** `logging_setup.redact()` masks passwords, API keys, phone
   numbers, email addresses, and `%APPDATA%` paths before they reach log sinks.

4. **`.env` is gitignored.** API keys are loaded from environment variables,
   never hardcoded.

5. **Future (Prompt 3):** ASR transcripts from the input layer must also be
   redacted before being passed to the LLM or logged.

## Caching and Sensitive Data

### LLM Response Cache

The ``LLMResponseCache`` (in ``agent_uia/performance/cache.py``) caches LLM
chat completions to avoid redundant API calls and reduce latency. Key security
properties:

1. **In-memory only.** The cache is a Python dictionary — never serialised to
   disk, never written to a file, never included in logs. When the application
   exits, all cached data is lost.
2. **Key derivation.** Cache keys are the hex-encoded SHA-256 hash of the
   JSON-serialised messages + model name. The original message content cannot
   be recovered from the key alone. The key itself is never logged or
   persisted.
3. **Content never persisted.** The cached ``LLMResponse`` objects exist only
   in process memory. No TTL expiry triggers a write to disk — expired
   entries are simply deleted from the dictionary.
4. **Opt-out.** Users can disable the LLM cache by setting
   ``cache.llm_enabled = false`` in the config file. This ensures every
   chat request reaches the API and no responses are reused across calls.

```toml
[cache]
llm_enabled = false
```

### Staleness Trade-off

The default TTL of 300 seconds (5 minutes) balances performance against
freshness:

- **Shorter TTL** (e.g. 30 s): safer for dynamic conversations where the
  LLM's answer could change moment-to-moment, but reduces cache hit rate.
- **Longer TTL** (e.g. 600 s): better performance for repetitive tasks
  (e.g. polling a UI element every few seconds) but risks serving a stale
  response.

Choose the TTL that matches your use case. For security-sensitive contexts
where LLM responses contain PII or credentials, disable the cache entirely.

### Control Tree Cache

The ``ControlTreeCache`` is a short-lived (default 3 s TTL) cache for
UI Automation control trees. It does **not** store window content, text
values, or any user data — only structural metadata (control type,
automation ID, bounding rectangle). This cache is also purely in-memory
and is invalidated on every user action via ``invalidate_on_action()``.

## Voice Input Privacy

### ASR (Automatic Speech Recognition)

- All speech recognition runs **entirely offline** on your machine via
  ``faster-whisper`` (CPU-only, no network connection during transcription).
- Audio buffers are kept **in memory only** — never written to disk.
  After transcription the buffer is explicitly freed: ``del audio; gc.collect()``.
- The model weights are downloaded from ``huggingface.co`` (or a configured mirror).
  **This is the only network access** during voice input. Users can choose
  an alternative mirror (e.g. ``hf-mirror.com`` for mainland China) in the
  first-run dialog.

### TTS (Text-to-Speech, opt-in)

- When enabled, TNT sends **only the final answer text** (already generated
  by the LLM) to Microsoft's Edge TTS endpoint.
- No audio, UI state, API keys, or personal data is included in the request.
- TTS is **opt-in** — users who disable it never make any network request for
  speech synthesis.

### Mic Indicator

- A **red mic indicator** (button color on the floating window) is visible
  whenever audio recording is active. The indicator cannot be suppressed by
  the agent — it is a hardwired UI element.

### User Control

- Model download can be deferred or skipped entirely — TNT works in text-only
  mode without any voice components.
- Downloaded models can be removed at any time via ``tnt model-delete <size>``.

## What This Version Does NOT Protect Against

This is an honest statement of limitations:

- **Physical access attacks.** An attacker with physical access to the machine
  can bypass any software-level safety mechanism.

- **Kernel-level malware.** If the OS or Python interpreter is compromised, the
  safety gate cannot be trusted.

- **DLL injection / hooking.** The `uiautomation` library calls Windows COM
  interfaces. A compromised COM proxy could intercept or spoof UIA calls.

- **Social engineering.** The agent executes the user's instructions. If the user
  is tricked into issuing a destructive command, the safety gate provides a
  confirmation prompt — but the user may still approve it.

## Confirmation Protocol

Every destructive or sensitive action (delete, send, pay, submit, transfer,
purchase, close_account, etc.) follows this flow:

```
LLM emits tool_call(click, delete_button)
Dispatcher checks: target is sensitive?
  → looks for preceding confirmation in tool message history
  → No confirmation found → returns REFUSED error
LLM receives the REFUSED error
  → next turn: emits tool_call(request_user_confirmation, delete_button)
Dispatcher routes to AppController → ConfirmationDialog pops up
  → User clicks "Yes"
  → Dispatcher returns "user said yes" to LLM
LLM re-emits tool_call(click, delete_button)
  → Dispatcher allows (confirmation is cached)
  → executor clicks the button
  → result returned
```

Key properties:

- **Server-side guard.** The ToolDispatcher refuses sensitive actions *before*
  they reach the executor. The LLM cannot bypass this check.
- **Audit trail.** Every confirmation request and response is logged to
  ``audit.log`` with the user's response (yes/no/stop/timeout).
- **Time-out.** If the user does not respond within 30 seconds (configurable),
  the action is refused and logged as "timeout".
- **Task abort.** The "Stop the whole task" button immediately aborts the
  current Planner task and returns a failure status.

## What This Version Does NOT Protect Against

- **Physical access attacks.** An attacker with physical access to the machine
  can bypass any software-level safety mechanism.

- **Kernel-level malware.** If the OS or Python interpreter is compromised, the
  safety gate cannot be trusted.

- **DLL injection / hooking.** The `uiautomation` library calls Windows COM
  interfaces. A compromised COM proxy could intercept or spoof UIA calls.

- **Social engineering.** The agent executes the user's instructions. If the user
  is tricked into issuing a destructive command, the safety gate provides a
  confirmation prompt — but the user may still approve it.

- **Supply-chain attacks on dependencies.** We pin minimum versions but do not
  (in this version) verify hashes or use a lockfile. This will be addressed in
  the packaging prompt.

- **Memory scraping.** The audit log and in-memory event buffer are not encrypted.
  A process with read access to the agent's memory could exfiltrate the audit trail.
