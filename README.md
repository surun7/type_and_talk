<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows%20only-0078D6?logo=windows&logoColor=white" alt="Windows only">
  <img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="Apache 2.0">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/status-🔄%20active%20dev-orange" alt="Active development">
  <img src="https://img.shields.io/badge/perf-optimized-brightgreen" alt="Performance optimized">
  <img src="https://img.shields.io/badge/voice-WASM%20ASR%20+%20Edge%20TTS-blueviolet" alt="Voice input">
  <img src="https://img.shields.io/badge/vision-none-darkgreen" alt="No vision">
  <img src="https://img.shields.io/badge/screenshots-zero-darkgreen" alt="No screenshots">
</p>

<h1 align="center">🖥️ Type and Talk (TNT)</h1>

<p align="center"><strong>Windows desktop AI agent — UIA only. No screenshots. No vision.</strong></p>

<p align="center">
  <sub>
    Tell your PC what to do in plain English. TNT sees what you see — through the
    <a href="https://learn.microsoft.com/en-us/windows/win32/winauto/">Windows UI Automation</a>
    accessibility tree — and acts on your behalf. No pixels, no OCR, no fragile
    coordinate-guessing. Just the structured UI tree + an LLM brain.
  </sub>
</p>

---

## ✨ What Is This?

**Type and Talk** is a desktop agent that turns natural language into real UI actions:

> *"Open Notepad, type 'Hello from TNT', and close it without saving."*

It uses the [Windows UI Automation](https://github.com/yinkaisheng/Python-UIAutomation-for-Windows) API
exclusively — the same accessibility interface used by screen readers. Instead of
screenshots and vision models, it reads the **UIA control tree**: buttons, text fields,
menus, and windows. Think of it as a screen-reader that can also *click* and *type*.

### Why UIA instead of screenshots?

| Approach | Screenshots + Vision | UIA (this project) |
|---|---|---|
| What it sees | Pixels | Structured control tree |
| Accuracy | ~85–95% (OCR errors) | ~100% on UIA-exposed apps |
| Speed | Slow (capture → infer → act) | Fast (query → act) |
| Privacy | Screenshots may leak to cloud | Only structured metadata leaves your PC |
| Cost | High (vision model tokens) | Low (text-only tokens) |
| Anti-cheat risk | Screenshots trigger bans | UIA is benign accessibility API |

---

## 🚀 Quick Start

```bash
# 1. Clone
git clone https://github.com/surun7/type_and_talk.git
cd type_and_talk

# 2. Install (Windows only!)
pip install -e ".[dev]"

# 3. Set your DeepSeek API key
cp .env.example .env
# Edit .env → fill in DEEPSEEK_API_KEY

# 4. Self-test (no LLM needed — opens & closes Notepad)
tnt doctor

# 5. Your first natural-language task
tnt run "Open Notepad, type 'Hello from TNT', and close it without saving."
```

> **Expected cost:** ~$0.0002 per task with `deepseek-flash`.

---

## 🖥️ Quick Start (GUI)

```bash
# Install with GUI dependencies
pip install -e ".[dev]"

# Launch the tray app
tnt
```

A tray icon appears in your system tray (green = idle). Press **Ctrl+Shift+Space**
to toggle the floating window. Type a command like "Open Notepad and type Hello"
and press Enter. The response streams in real time.

- The floating window auto-hides on success (configurable).
- Right-click the tray icon for **Pause Agent** (toggles a paused state) and **Quit**.
- Tray icon color reflects agent state: green (idle), yellow (thinking), gray (paused), red (error).

---

## 📝 First-Run Notes

- **Global hotkey:** No special permissions required on Windows. If
  ``Ctrl+Shift+Space`` is taken by another app, change it by editing
  ``AppConfig.hotkey`` in the source (config file loading comes later).

- **API key:** On first ``run_task`` without ``DEEPSEEK_API_KEY`` set, the
  floating window shows a clear error. Set it via:
  ```bash
  set DEEPSEEK_API_KEY=sk-...
  ```
  Or create a ``.env`` file with ``DEEPSEEK_API_KEY=sk-...`` in the project root.

- **Offscreen testing:** Run ``tnt ui-smoke`` for a headless GUI self-test that
  verifies the floating window, status bar, and response area work end-to-end
  with a mocked Planner.

---

## 🧠 How It Works

```
User says "Open Notepad, type hello"
                │
    ┌───────────▼───────────┐
    │     SAFETY GATE       │  ← Immutable frontline. Blocks games, login screens,
    │  (singleton, no-bypass)│    sensitive actions. Audit log. Un-bypassable.
    └───────────┬───────────┘
                │ ALLOW
    ┌───────────▼───────────┐
    │    LLM PLANNER        │  ← ReAct loop. Thinks, calls tools, observes.
    │  (DeepSeek, ReAct)    │    Max 20 steps. $0.10 budget cap.
    └───────────┬───────────┘
                │ tool calls
    ┌───────────▼───────────┐
    │   UIA EXECUTOR        │  ← Hands. 14 tools: click, type, find windows,
    │  (uiautomation)       │    read control trees, launch apps. All UIA.
    └───────────┬───────────┘
                │
    ┌───────────▼───────────┐
    │   AUDIT + COST LOGS   │  ← ./logs/audit.log + ./logs/usage.jsonl
    └───────────────────────┘
```

### ReAct Loop in One Diagram

```
  System Prompt ──▶ LLM thinks ──▶ tool_call: launch_app("notepad.exe")
                                       │
                          ToolMessage ◀─┘ result: {ok: true, pid: 123}
                          (appended to history)
                                       │
                          LLM thinks ──▶ tool_call: wait_for_window("Notepad")
                                       │
                          ToolMessage ◀─┘ result: {ok: true, window: {...}}
                                       │
                          LLM thinks ──▶ Final answer: "Notepad is open."
```

---

## 🔒 Safety by Design

TNT treats the LLM as **untrusted input**. Every action flows through a safety gate that:

- 🚫 **Blocks game clients** (Valorant, League, Steam, etc. — 35+ executables)
- 🔑 **Refuses login screens** (won't type credentials — log in manually first)
- ⚠️ **Requires confirmation** for destructive actions (delete, send, purchase)
- 📝 **Appends to immutable audit log** (every decision recorded)

See [`docs/SECURITY.md`](docs/SECURITY.md) for the full threat model.

### Sensitive Actions — Confirmation Flow

For destructive actions (delete, send, pay, submit, transfer, purchase, etc.),
a **real modal dialog** pops up with full context:

- Action type (e.g. "delete")
- Target identifier (e.g. "Delete button in Outlook")
- Risk explanation ("This will permanently move the selected email to Trash")
- Countdown timer (default 30s — auto-refuses if no response)

Three buttons: **Yes, do it** (Enter), **No, skip** (Esc), **Stop the whole task**
(aborts the current Planner task). Every response is logged to ``audit.log``.

If the LLM attempts a sensitive action without calling ``request_user_confirmation``
first, the ToolDispatcher refuses it **before** reaching the executor — this is
a hard server-side guard that the LLM cannot bypass.

---

## 📋 Hard Constraints

| # | Rule |
|---|---|
| 🪟 | **Windows only** — refuses to import on macOS/Linux |
| 🌳 | **UIA only** — zero `pyautogui`, `pynput`, `mss`, `PIL`, `opencv` |
| 📸 | **No screenshots** — CI-enforced, not even optional |
| 👁️ | **No vision models** — the LLM sees the UIA tree, not pixels |
| 🛡️ | **Safety gate is un-bypassable** — every executor method calls it first |
| 🧩 | **No app-specific code** — the LLM discovers everything via UIA at runtime |

---

## 💰 Cost & Limits

| Parameter | Default | Where to change |
|---|---|---|
| Max steps per task | 20 | `PlannerConfig.max_steps` |
| Max cost per task | $0.10 | `PlannerConfig.max_cost_usd_per_task` |
| Model | `deepseek-flash` | `DEEPSEEK_MODEL` in `.env` |
| Flash pricing | $0.014 / $0.028 per 1M tokens | `pricing.json` |
| Chat pricing | $0.14 / $0.28 per 1M tokens | `pricing.json` |

---

## ⚡ Performance

TNT includes a built-in performance monitoring system that tracks latency,
memory usage, and cache efficiency in real time.

| Metric | Target |
|---|---|
| Cold start (app → ready) | ≤ 1.5 s |
| Hotkey → window visible | ≤ 100 ms |
| LLM response cache hit | ≤ 5 ms |
| Control tree cache hit | ≤ 1 ms |
| Memory (idle) | ≤ 250 MB RSS |
| Memory (during task) | ≤ 600 MB RSS |

- **Performance tab** in the GUI main window shows live charts for LLM
  call duration, cache hit rate, control tree fetch time, and memory RSS.
- **`tnt perf`** CLI command runs a task and prints phase-level timing.
- **`tnt perf-tail`** tails live metrics from `logs/perf.jsonl`.
- **LLM response cache** (default 5 min TTL) avoids redundant API calls.
- **Control tree cache** (default 3 s TTL) avoids repeated UIA enumeration.

See [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) for the full tuning guide,
including how to read each chart, common bottlenecks, and profiling
slow tasks.

---

## 🎤 Voice Input

TNT supports optional voice input via a Push-to-Talk (PTT) hotkey (Ctrl+Shift+V by default).

### First Run

On first launch, if no ASR model is installed, TNT shows an onboarding dialog:
- Choose a model size: tiny (75 MB), base (140 MB, recommended), or small (460 MB).
- Choose a download mirror: huggingface.co (default) or hf-mirror.com (China-friendly).
- The download takes ~1-3 minutes on broadband and is **resumable**.
- You can skip and use text-only mode.

### Model Sizes

| Size | Size on Disk | Accuracy | Speed |
|---|---|---|---|
| tiny | ~75 MB | Basic | Fastest |
| base | ~140 MB | Good (recommended) | Fast |
| small | ~460 MB | Better | Moderate |
| medium | ~1.5 GB | High | Slow |
| large-v3 | ~3 GB | Best | Slowest |

Models can be switched later via `tnt model-download <size>`.

### Usage

1. Hold **Ctrl+Shift+V** (configurable) — a red indicator shows recording is active.
2. Speak your command.
3. Release — the audio is transcribed locally and submitted as text.
4. If **TTS** is enabled (opt-in), the agent speaks the final answer back.

### Privacy

- All speech recognition runs **entirely offline** on your machine.
- Audio data is held in memory only, never written to disk.
- TTS (opt-in) sends only the final response text to Microsoft's Edge TTS endpoint.
- A visible mic indicator is shown whenever recording is active.

### CLI Commands

```bash
tnt asr-smoke              # Record 5s and transcribe (test)
tnt tts-smoke "..."        # Speak text via TTS
tnt model-download base    # Pre-download a model
tnt model-list             # List all models and their status
tnt model-delete base      # Remove a downloaded model
```

### Known Limitations
- No wake-word detection.
- Full-utterance transcription (not real-time streaming).
- Whisper may hallucinate on silence; post-processing strips common patterns.

---

## 🛠️ CLI Reference

```bash
tnt run "instruction"     # Single-shot: plan → execute → report
tnt chat                  # Interactive REPL (coming in Prompt 3)
tnt demo                  # UIA smoke test with Notepad (no LLM)
tnt doctor                # Self-test: platform → safety → executor → Notepad
tnt asr-smoke             # Record 5 s and transcribe (ASR smoke test)
tnt tts-smoke "..."       # Synthesize text to speech and play
tnt perf "instruction"    # Run a task and show phase-level timing
tnt perf-tail             # Tail live metrics from logs/perf.jsonl
tnt model-download base   # Pre-download a Whisper model
tnt model-list            # List all models and their status
tnt model-delete base     # Remove a downloaded model
tnt --version             # Print version
```

---

## 📁 Project Structure

```
type_and_talk/
├── src/agent_uia/
│   ├── safety.py             # Safety gate (singleton, immutable)
│   ├── executor.py           # UIA wrapper (hands)
│   ├── llm_client.py         # DeepSeek client + usage ledger
│   ├── tools.py              # 14 tool specs + dispatcher
│   ├── planner.py            # ReAct loop (brain)
│   ├── prompts/
│   │   └── system_prompt.md  # LLM system prompt (editable!)
│   ├── audio/                  # Voice input/output pipeline
│   │   ├── model_manager.py    # Download/cache Whisper model weights
│   │   ├── recognizer.py       # faster-whisper speech-to-text
│   │   ├── recorder.py         # sounddevice audio capture
│   │   ├── vad.py              # Voice activity detection
│   │   └── synthesizer.py      # Edge TTS (opt-in)
│   ├── pricing.json          # Model cost table
│   ├── demo.py               # Demo with --llm / --no-llm
│   └── main.py               # CLI entry (tnt command)
├── tests/                    # pytest suite (~70 tests)
├── docs/
│   ├── ARCHITECTURE.md       # Pipeline diagram + design rationale
│   ├── SECURITY.md           # Threat model + mitigations
│   └── PERFORMANCE.md        # Performance tuning guide
├── pyproject.toml
└── LICENSE
```

---

## 🗺️ Roadmap

- ✅ **Done:** Safety gate, UIA executor, LLM planner, 14 tools, CLI, demo, GUI shell (tray, floating window, hotkey), Voice input (Whisper ASR, PTT, first-run download, opt-in Edge TTS), Performance monitoring (cache, metrics, perf tab)
- ⬜ **Next:** Interactive REPL (`tnt chat`), main settings window
- ⬜ **Later:** Skill system, packaging (MSI), CI/CD

---

## 🤝 Contributing

Pre-alpha — not accepting external PRs yet. But feedback is welcome!
Open an issue with ideas, bug reports, or UIA edge cases you've found.

---

<p align="center">
  <sub>Built with ☕ on Windows. Apache 2.0 © 2026
  <a href="https://github.com/surun7">surun7</a></sub>
</p>
