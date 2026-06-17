<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows%20only-0078D6?logo=windows&logoColor=white" alt="Windows only">
  <img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="Apache 2.0">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/status-pre--alpha-red" alt="Pre-alpha">
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

## 🛠️ CLI Reference

```bash
tnt run "instruction"     # Single-shot: plan → execute → report
tnt chat                  # Interactive REPL (coming in Prompt 3)
tnt demo                  # UIA smoke test with Notepad (no LLM)
tnt doctor                # Self-test: platform → safety → executor → Notepad
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
│   ├── pricing.json          # Model cost table
│   ├── demo.py               # Demo with --llm / --no-llm
│   └── main.py               # CLI entry (tnt command)
├── tests/                    # pytest suite (~65 tests)
├── docs/
│   ├── ARCHITECTURE.md       # Pipeline diagram + design rationale
│   └── SECURITY.md           # Threat model + mitigations
├── pyproject.toml
└── LICENSE
```

---

## 🗺️ Roadmap

- ✅ **Done:** Safety gate, UIA executor, LLM planner, 14 tools, CLI, demo
- ⬜ **Next:** Interactive REPL (`tnt chat`), input layer, streaming UX
- ⬜ **Later:** Packaging (MSI), CI/CD, ASR input

---

## 🤝 Contributing

Pre-alpha — not accepting external PRs yet. But feedback is welcome!
Open an issue with ideas, bug reports, or UIA edge cases you've found.

---

<p align="center">
  <sub>Built with ☕ on Windows. Apache 2.0 © 2026
  <a href="https://github.com/surun7">surun7</a></sub>
</p>
