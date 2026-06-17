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

- **Supply-chain attacks on dependencies.** We pin minimum versions but do not
  (in this version) verify hashes or use a lockfile. This will be addressed in
  the packaging prompt.

- **Memory scraping.** The audit log and in-memory event buffer are not encrypted.
  A process with read access to the agent's memory could exfiltrate the audit trail.
