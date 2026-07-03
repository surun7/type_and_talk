<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows%20only-0078D6?logo=windows&logoColor=white" alt="Windows only">
  <img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="Apache 2.0">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/status-🔄%20active%20dev-orange" alt="Active development">
  <img src="https://img.shields.io/badge/perf-optimized-brightgreen" alt="Performance optimized">
  <img src="https://img.shields.io/badge/voice-Whisper%20ASR%20+%20Edge%20TTS-blueviolet" alt="Voice input">
  <img src="https://img.shields.io/badge/skills-YAML%20based-blue" alt="Skill system">
  <img src="https://img.shields.io/badge/vision-none-darkgreen" alt="No vision">
  <img src="https://img.shields.io/badge/screenshots-zero-darkgreen" alt="No screenshots">
</p>

<h1 align="center">🖥️ Type and Talk (TNT)</h1>

<p align="center"><strong>Windows desktop AI agent — UIA driven. Voice controlled. Skill extensible.</strong></p>

<p align="center">
  <sub>
    Tell your PC what to do in plain English or voice. TNT sees what you see — through the
    <a href="https://learn.microsoft.com/en-us/windows/win32/winauto/">Windows UI Automation</a>
    accessibility tree — and acts on your behalf. No pixels, no OCR, no fragile
    coordinate-guessing. Just the structured UI tree + an LLM brain.
  </sub>
</p>

---

## ✨ What Is This?

**Type and Talk** is a desktop agent that turns natural language and voice into real UI actions:

> *"打开记事本，输入 'Hello from TNT'，不保存关闭。"*
> *(Press Ctrl+Shift+V and say it.)*

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

# To use CPU-only PyTorch for voice (smaller download):
# pip install torch --index-url https://download.pytorch.org/whl/cpu

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
pip install -e ".[dev]"
tnt
```

A tray icon appears (green = idle). On first launch the **main window** opens automatically.

### Hotkeys
| Key | Action |
|---|---|
| **Ctrl+Shift+Space** | Toggle floating chat window |
| **Ctrl+Shift+V** | Push-to-Talk (hold to record, release to transcribe) |
| **Ctrl+Shift+M** | Toggle main window |

### Main Window (6 Tabs)
| Tab | What it does |
|---|---|
| 🏠 **Home** | Quick input, recent activity, one-click shortcuts |
| 💬 **History** | Searchable conversation log, pagination, CSV export |
| ⚡ **Skills** | Install & run YAML-based automation skills (5 built-in) |
| ⚙️ **Settings** | API key, hotkeys, ASR model, TTS, theme, planner limits |
| 📊 **Usage** | Token/cost stats, daily charts, pyqtgraph histograms |
| 📈 **Performance** | Real-time latency, cache hit rates, memory monitor |

---

## 🎤 Voice Input

TNT supports optional voice input via Push-to-Talk (**Ctrl+Shift+V**).

- **First run:** download wizard (~140 MB for `base` model, resumable, 1-3 min)
- **Offline:** all recognition runs locally via `faster-whisper`
- **VAD:** silero-vad (ML-based, auto-downloads ~2 MB model) with RMS fallback
- **TTS:** opt-in Edge TTS (`zh-CN-XiaoxiaoNeural` default)
- **Model sizes:** `tiny` (75 MB), `base` (140 MB, recommended), `small` (460 MB), `medium` (1.5 GB), `large-v3` (3 GB)
- **Configurable:** model size, download mirror (`hf-mirror.com` for China), PTT hotkey

---

## ⚡ Skill System

Skills are YAML files that orchestrate tool calls without an LLM — fast, cheap, deterministic.

- **5 built-in skills:** Open Notepad, Open Calculator, List Windows, Minimize All, Lock Workstation
- **3 demo skills:** Format Clipboard Text, Organize Desktop Files, Show System Info
- **Install:** drop a `.yaml` file into `%LOCALAPPDATA%/agent-uia/skills/` or use `tnt skills install`
- **Safety:** every tool call still goes through the safety gate. No code execution from YAML.
- **Decision steps:** `asteval`-sandboxed expressions for branching logic

### CLI
```bash
tnt skills list              # Show all installed skills
tnt skills show open-notepad # View YAML source
tnt skills run open-notepad  # Execute a skill
tnt skills install ./my-skill.yaml
tnt skills install https://example.com/skill.yaml
tnt skills uninstall my-skill
```

---

## ⚡ Performance

TNT includes a built-in performance monitoring system.

| Metric | Target |
|---|---|
| Cold start (app → ready) | ≤ 1.5 s |
| Hotkey → window visible | ≤ 100 ms |
| LLM response cache hit | ≤ 5 ms |
| Control tree cache hit | ≤ 1 ms |
| Memory (idle) | ≤ 250 MB RSS |

- **LLM response cache** (SHA-256 key, 5 min TTL, in-memory only)
- **Control tree cache** (3 s TTL, auto-invalidated on actions)
- **Performance tab** in main window: live charts, event table, export to JSON
- **`tnt perf`** / **`tnt perf-tail`**: headless CLI inspection

---

## 🧠 How It Works

```
User (text or voice)
         │
    ┌────▼────┐
    │  SAFETY  │  ← Blocks games, login screens, dangerous executables
    │   GATE   │     Requires confirmation for delete/move/pay/…
    └────┬────┘
         │ ALLOW
    ┌────▼────┐
    │ PLANNER │  ← ReAct loop (DeepSeek, max 20 steps, $0.10 budget)
    │  (LLM)  │     OR SkillRunner (YAML → tool calls, no LLM cost)
    └────┬────┘
         │ tool calls
    ┌────▼────┐
    │ TOOL    │  ← 21 tools: UIA (click/type/find/…) + system
    │DISPATCH │    (clipboard/file/system_info/llm_complete)
    └────┬────┘
         │
    ┌────▼────┐
    │  UIA    │  ← Windows UI Automation (the actual hands)
    │EXECUTOR │
    └─────────┘
```

All 21 tools:
- **UIA:** `launch_app`, `find_window`, `list_windows`, `get_control_tree`, `click`, `type_text`, `set_value`, `invoke`, `press_key`, `wait_for_window`, `wait_for_control`, `close_window`, `read_screen_state`, `request_user_confirmation`
- **System:** `clipboard_read`, `clipboard_write`, `file_list`, `file_mkdir`, `file_move`, `system_info`, `llm_complete`

---

## 🛠️ CLI Reference

```bash
# Core
tnt run "<instruction>"       # Single-shot: plan → execute → report
tnt chat                      # Interactive REPL (coming)
tnt doctor                    # System self-test (no LLM)
tnt demo                      # UIA smoke test with Notepad

# GUI
tnt                           # Launch tray + main window

# Voice / ASR
tnt asr-smoke                 # Record 5s and transcribe
tnt tts-smoke "..."           # Text-to-speech test
tnt model-download base       # Pre-download a Whisper model
tnt model-list                # List all models and their status
tnt model-delete base         # Remove a downloaded model

# Skills
tnt skills list               # Show installed skills
tnt skills show open-notepad  # View YAML source
tnt skills run open-notepad   # Execute a skill
tnt skills install <path|url> # Install a skill
tnt skills uninstall <id>     # Remove a user skill

# Performance
tnt perf                      # Print performance summary
tnt perf-tail <N>             # Show last N perf events
tnt perf-reset                # Clear perf log
tnt cache-clear               # Clear in-memory caches

# Config
tnt config-show               # Print config (API key masked)
tnt config-edit               # Open config in editor
tnt config-path               # Print config file path

# Testing
tnt e2e                       # Run end-to-end test suite
tnt ui-smoke                  # GUI smoke test (offscreen)
tnt --version                 # Print version
```

---

## 📁 Project Structure

```
type_and_talk/
├── src/agent_uia/
│   ├── safety.py                    # Safety gate (singleton, immutable)
│   ├── executor.py                  # UIA wrapper + performance hooks
│   ├── llm_client.py                # DeepSeek client + usage ledger + cache
│   ├── planner.py                   # ReAct loop (brain) + perf instrumentation
│   ├── config.py                    # TOML-backed persistence
│   ├── paths.py                     # Centralized paths (%LOCALAPPDATA%)
│   ├── tools.py → tools/            # 21 tool specs + dispatcher
│   │   ├── specs/                   #   Per-tool Pydantic models
│   │   ├── dispatcher.py            #   Safety gate + dispatch logic
│   │   └── registry.py              #   Tool registration
│   ├── skills/                      # YAML skill system
│   │   ├── schema.py                #   Pydantic skill models
│   │   ├── parser.py                #   YAML → Skill
│   │   ├── runner.py                #   Skill executor (bypasses LLM)
│   │   ├── loader.py                #   Registry (builtin + user)
│   │   ├── context.py               #   Variable engine
│   │   └── builtin/                 #   8 built-in skills (.yaml)
│   ├── audio/                       # Voice input/output
│   │   ├── model_manager.py         #   Download/cache Whisper
│   │   ├── recognizer.py            #   faster-whisper ASR
│   │   ├── recorder.py              #   sounddevice capture
│   │   ├── vad.py                   #   silero-vad / RMS fallback
│   │   └── synthesizer.py           #   Edge TTS (opt-in)
│   ├── performance/                 # Performance monitoring
│   │   ├── monitor.py               #   Ring-buffer metrics
│   │   └── cache.py                 #   LLM + control tree caches
│   ├── prompts/
│   │   └── system_prompt.md         # LLM system prompt
│   ├── ui/                          # Qt6 GUI
│   │   ├── app_controller.py        #   Glue layer (Planner + UI)
│   │   ├── main_window.py           #   1100×720 main window
│   │   ├── sidebar.py               #   6-tab navigation
│   │   ├── main_content.py          #   QStackedWidget
│   │   ├── floating_window.py       #   Spotlight-like chat
│   │   ├── theme.py                 #   Dark/Light theme engine
│   │   ├── tray.py                  #   System tray icon
│   │   ├── hotkey.py                #   Win32 hotkeys (N simultaneous)
│   │   ├── first_run_dialog.py      #   ASR download wizard
│   │   ├── confirmation_dialog.py   #   Sensitive-action modal
│   │   └── tabs/                    #   The 6 tab widgets
│   ├── logging_setup.py             # Loguru + redaction
│   ├── pricing.json                 # Model cost table
│   ├── demo.py                      # Demo with --llm / --no-llm
│   └── main.py                      # CLI entry (tnt command)
├── tests/                           # pytest suite (175+ tests)
│   ├── e2e/                         # End-to-end skill tests
│   └── test_*.py
├── docs/
│   ├── ARCHITECTURE.md              # Full architecture + diagrams
│   ├── SECURITY.md                  # Threat model + mitigations
│   ├── PERFORMANCE.md               # Performance tuning guide
│   ├── SKILL_AUTHORING.md           # How to write YAML skills
│   ├── VIDEO_DEMO.md                # 90s video script
│   └── DEMO_GALLERY.md              # Reproducible demo scenarios
├── pyproject.toml
└── LICENSE
```

---

## 📝 Config Persistence

All persistent data lives under `%LOCALAPPDATA%\agent-uia\`:

| Path | Contents |
|---|---|
| `config.toml` | All settings (API key, hotkeys, ASR, TTS, theme, planner limits) |
| `logs/audit.log` | Every safety decision (JSON lines) |
| `logs/usage.jsonl` | Per-task token/cost ledger |
| `logs/perf.jsonl` | Performance metrics (30s flush) |
| `history.jsonl` | Conversation history (auto-rotated at 5 MB) |
| `models/` | Downloaded Whisper model weights |
| `skills/` | User-installed skill YAML files |

---

## 🔒 Safety by Design

TNT treats the LLM as **untrusted input**. Every action flows through a safety gate:

- 🚫 **Blocks game clients** + **high-risk executables** (cmd, powershell, wscript, mshta…)
- 🔑 **Refuses login screens** (won't type credentials — log in manually)
- ⚠️ **Requires confirmation** for destructive actions (delete, file_move, pay, …)
- 📁 **File tools restricted to `%USERPROFILE%/{Desktop,Documents,…}`**
- 🛡️ **Extension blocklist** for file_move (`.exe`, `.bat`, `.ps1`, …)
- 📝 **Immutable audit log** — every decision recorded
- 🧩 **Skills are pure YAML** — no embedded code, no `eval()`, no `exec()`

See [`docs/SECURITY.md`](docs/SECURITY.md) for the full threat model.

---

## 🗺️ Roadmap

- ✅ **Done:** Safety gate, UIA executor, LLM planner, 21 tools, CLI, GUI shell (tray, floating window, hotkey, main window), Voice input (Whisper ASR, PTT, first-run wizard, opt-in TTS), Skill system (YAML schema, runner, registry, 8 built-in skills), Performance optimization (caching, monitoring, perf tab), End-to-end demo framework
- ⬜ **Next:** Interactive REPL (`tnt chat`), skill marketplace
- ⬜ **Later:** Packaging (MSI), CI/CD

---

## 🤝 Contributing

Pre-alpha — not accepting external PRs yet. But feedback is welcome!
Open an issue with ideas, bug reports, or UIA edge cases you've found.

---

<p align="center">
  <sub>Built with ☕ on Windows. Apache 2.0 © 2026
  <a href="https://github.com/surun7">surun7</a></sub>
</p>
