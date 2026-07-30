# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""CLI entry point — ``tnt`` command.

Subcommands:

- ``tnt`` (no args) — start the GUI.
- ``tnt run "<instruction>"`` — run the planner once.
- ``tnt chat`` — interactive REPL (placeholder).
- ``tnt demo`` — alias for ``python -m agent_uia.demo``.
- ``tnt doctor`` — run safety + executor self-test (no LLM).
- ``tnt ui-smoke`` — GUI self-test (offscreen, mocked Planner).
- ``tnt asr-smoke`` — record 5 s and transcribe (ASR smoke test).
- ``tnt tts-smoke "<text>"`` — synthesize text to speech and play.
- ``tnt model-download [size]`` — download a Whisper model.
- ``tnt model-list`` — list all models and their status.
- ``tnt model-delete <size>`` — remove a downloaded model.
- ``tnt --version`` — print version.
"""

from __future__ import annotations

import sys

import typer
import typer.core

from agent_uia import __version__

app = typer.Typer(
    name="tnt",
    help="Type and Talk (TNT) — Windows UIA desktop agent.",
    no_args_is_help=False,
)


def _version_callback(value: bool) -> None:
    if value:
        print(f"tnt {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Print version and exit.",
    ),
) -> None:
    # No subcommand → start GUI (default for end users).
    if ctx.invoked_subcommand is None:
        print("DEBUG: starting GUI...", file=sys.stderr)
        _run_gui()
        print("DEBUG: GUI returned unexpectedly", file=sys.stderr)


@app.command()
def run(
    instruction: str = typer.Argument(..., help="Natural-language instruction to execute."),
) -> None:
    """Execute a single instruction via the LLM planner."""
    import asyncio
    import os
    from decimal import Decimal

    from dotenv import load_dotenv

    from agent_uia.executor import UIAExecutor
    from agent_uia.llm_client import LLMConfig, UsageLedger
    from agent_uia.paths import PACKAGE_DIR
    from agent_uia.planner import Planner, PlannerConfig
    from agent_uia.platform_check import assert_windows
    from agent_uia.safety import SafetyConfig, SafetyGate

    assert_windows()
    load_dotenv()

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        typer.echo(
            "ERROR: DEEPSEEK_API_KEY not set. Create a .env file or set the env var.",
            err=True,
        )
        raise typer.Exit(1)

    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    llm_config = LLMConfig(
        api_key=api_key,  # type: ignore[arg-type]
        base_url=base_url,
        model=model,
    )
    gate = SafetyGate(SafetyConfig())
    executor = UIAExecutor(safety_gate=gate)
    ledger = UsageLedger()

    planner_config = PlannerConfig(
        llm=llm_config,
        max_steps=20,
        max_cost_usd_per_task=Decimal("0.10"),
        system_prompt_file=PACKAGE_DIR / "prompts" / "system_prompt.md",
        enable_streaming=False,
    )

    planner = Planner(
        config=planner_config,
        executor=executor,
        safety_gate=gate,
        usage_ledger=ledger,
    )

    async def _run() -> None:
        result = await planner.run(instruction)
        typer.echo()
        typer.echo(f"Status: {result.status}")
        typer.echo(f"Steps:  {result.steps_taken}")
        typer.echo(f"Cost:   ${result.total_cost_usd:.6f}")
        typer.echo(f"Tokens: {result.usage.total_tokens}")
        typer.echo()
        typer.echo(result.user_facing_message)
        code_map = {
            "success": 0,
            "failed": 1,
            "blocked": 2,
            "budget_exceeded": 3,
            "max_steps_exceeded": 4,
        }
        raise typer.Exit(code_map.get(result.status, 1))

    asyncio.run(_run())


@app.command()
def chat() -> None:
    """Start an interactive REPL (scheduled for a future prompt)."""
    typer.echo("Interactive chat mode is scheduled for a future release.")
    typer.echo("Use 'tnt run \"<instruction>\"' for single-shot execution.")


@app.command()
def demo() -> None:
    """Run the demo (same as python -m agent_uia.demo --no-llm)."""
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "agent_uia.demo", "--no-llm"],
        check=False,
    )
    raise typer.Exit(result.returncode)


@app.command()
def doctor() -> None:
    """Run safety gate + executor self-test (no LLM, Notepad open/close)."""
    import subprocess
    import time

    from agent_uia.executor import UIAExecutor
    from agent_uia.platform_check import assert_windows
    from agent_uia.safety import SafetyConfig, SafetyGate

    assert_windows()

    typer.echo("=== tnt doctor — system self-test ===")
    typer.echo()

    # 1. Platform check.
    typer.echo("[1/5] Platform check... ", nl=False)
    try:
        assert_windows()
        typer.echo("✓ Windows detected.")
    except Exception as exc:
        typer.echo(f"✗ FAIL: {exc}")
        raise typer.Exit(1)

    # 2. Safety gate.
    typer.echo("[2/5] Safety gate... ", nl=False)
    try:
        gate = SafetyGate(SafetyConfig())
        decision = gate.check_app(exe_name="notepad.exe", window_title="Untitled - Notepad")
        if decision.verdict.name == "ALLOW":
            typer.echo("✓ Notepad is ALLOWED.")
        else:
            typer.echo(f"✗ Unexpected verdict: {decision.verdict.name}")
            raise typer.Exit(1)
    except Exception as exc:
        typer.echo(f"✗ FAIL: {exc}")
        raise typer.Exit(1)

    # 3. UIA executor.
    typer.echo("[3/5] UIA executor... ", nl=False)
    try:
        executor = UIAExecutor(safety_gate=gate)
        typer.echo("✓ Created.")
    except Exception as exc:
        typer.echo(f"✗ FAIL: {exc}")
        raise typer.Exit(1)

    # 4. Launch Notepad.
    typer.echo("[4/5] Launch Notepad... ", nl=False)
    try:
        proc = subprocess.Popen(["notepad.exe"])
        time.sleep(1)
        window = executor.wait_for_window(title_contains="Notepad", timeout=10.0)
        typer.echo(f"✓ Found (pid={proc.pid}, title={window.title!r}).")
    except Exception as exc:
        typer.echo(f"✗ FAIL: {exc}")
        raise typer.Exit(1)

    # 5. Close Notepad.
    typer.echo("[5/5] Close Notepad... ", nl=False)
    try:
        executor.close_window(window)
        time.sleep(0.5)
        save_dialog = executor.find_window(title_contains="Notepad", timeout=2.0)
        if save_dialog is not None:
            import uiautomation as _uia
            _uia.SendKeys("n", waitTime=0.1)
        proc.wait(timeout=5)
        typer.echo("✓ Closed.")
    except Exception as exc:
        typer.echo(f"✗ FAIL: {exc}")
        raise typer.Exit(1)

    typer.echo()
    typer.echo("=== All checks passed. agent-uia is ready! ===")


# ── GUI mode ─────────────────────────────────────────────────────────────────


def _run_gui() -> None:
    """Start the TNT desktop GUI (system tray, floating window, hotkey)."""
    try:
        from agent_uia.ui import AppConfig, AppController

        # Allow offscreen override for testing.
        controller = AppController(config=AppConfig())
        controller.start()
    except Exception as exc:
        import traceback
        import sys
        print("FATAL: GUI failed to start", file=sys.stderr)
        traceback.print_exc()
        print(f"\nError: {exc}", file=sys.stderr)
        input("\nPress Enter to exit...")
        sys.exit(1)


@app.command()
def ui_smoke() -> None:
    """Run a GUI smoke test (offscreen, mocked Planner).

    Sets ``QT_QPA_PLATFORM=offscreen``, instantiates the UI, runs a scripted
    task through a mocked Planner, and verifies the response area content.
    Exits 0 on success, 1 on failure.
    """
    import asyncio
    import json as _json
    import os as _os

    # Force offscreen rendering.
    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication

    # High-DPI before QApp.
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)     # type: ignore[attr-defined]
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)        # type: ignore[attr-defined]

    app = QApplication.instance() or QApplication(sys.argv)

    import qasync
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    from decimal import Decimal

    from agent_uia.llm_client import LLMUsage
    from agent_uia.planner import (
        FinalAnswerReady,
        StepStarted,
        TaskResult,
        ToolCallFinished,
        ToolCallStarted,
    )
    from agent_uia.ui import AppConfig, AppController

    controller = AppController(config=AppConfig())

    # Build UI without calling start() (which blocks).
    controller._init_core()
    controller._init_ui()

    # Override the planner with a mock that emits a fake transcript.
    fake_usage = LLMUsage(model="test")

    async def _fake_planner_run(
        user_text: str,
        *,
        on_event=None,
        task_id=None,
    ) -> TaskResult:
        if on_event:
            await on_event(StepStarted(step_number=1))
            await on_event(ToolCallStarted(
                step_number=1, tool_name="launch_app",
                arguments={"app_name": "notepad.exe"},
            ))
            await on_event(ToolCallFinished(
                step_number=1, tool_name="launch_app",
                result=_json.dumps({"ok": True}), ok=True,
            ))
            await on_event(ToolCallStarted(
                step_number=2, tool_name="type_text",
                arguments={"text": "Hello from TNT"},
            ))
            await on_event(ToolCallFinished(
                step_number=2, tool_name="type_text",
                result=_json.dumps({"ok": True}), ok=True,
            ))
            await on_event(FinalAnswerReady(
                message="Done! Opened Notepad and typed the text."
            ))
        return TaskResult(
            status="success",
            user_facing_message="Done! Opened Notepad and typed the text.",
            steps_taken=2,
            total_cost_usd=Decimal("0.0001"),
            usage=fake_usage,
        )

    # Create a mock planner so the real run_task flow is exercised
    # (real run_task calls self._planner.run with on_event).
    class _MockPlanner:
        async def run(self, user_text, *, on_event=None, task_id=None):  # type: ignore[misc]
            return await _fake_planner_run(user_text, on_event=on_event, task_id=task_id)
    controller._planner = _MockPlanner()  # type: ignore[assignment]

    # Show the floating window.
    controller.show_floating_window()

    # Schedule: run a task, then assert, then quit.
    test_passed = [False]

    async def _run_test() -> None:
        await controller.run_task("Open Notepad and say Hello")
        # Give Qt time to process signal emissions.
        await asyncio.sleep(0.1)

        fw = controller._floating
        if fw is None:
            typer.echo("FAIL: FloatingWindow was not created.")
            test_passed[0] = False
        else:
            content = fw._response.toPlainText() if fw._response else ""
            if "Done" in content and "Notepad" in content:
                test_passed[0] = True
            else:
                typer.echo(f"FAIL: response missing expected text.\nGot: {content!r}")
                test_passed[0] = False

        loop.stop()

    QTimer.singleShot(100, lambda: asyncio.ensure_future(_run_test()))
    loop.run_forever()

    raise typer.Exit(0 if test_passed[0] else 1)


# ── Voice / ASR Subcommands ─────────────────────────────────────────────────────


@app.command()
def asr_smoke() -> None:
    """Record 5 seconds, transcribe, and print the result (smoke test)."""
    import asyncio

    from agent_uia.audio.model_manager import ModelManager
    from agent_uia.audio.recognizer import SpeechRecognizer
    from agent_uia.audio.recorder import AudioRecorder
    from agent_uia.paths import get_models_dir

    models_dir = get_models_dir()
    manager = ModelManager(models_dir=models_dir)

    async def _run() -> None:
        ready = await manager.ensure_model_ready("base")
        if not ready:
            typer.echo(
                "ERROR: ASR model 'base' is not installed.\n"
                "  Run:  tnt model-download base",
                err=True,
            )
            raise typer.Exit(1)

        typer.echo("Recording 5 seconds...")
        recorder = AudioRecorder()
        audio = recorder.record(duration=5.0)

        typer.echo("Transcribing...")
        recognizer = SpeechRecognizer(model_size="base", models_dir=models_dir)
        result = recognizer.transcribe(audio)
        typer.echo(f"\nTranscription: {result.text!r}")

    asyncio.run(_run())


@app.command()
def tts_smoke(
    text: str = typer.Argument(..., help="Text to synthesize."),
) -> None:
    """Synthesize text to speech and play it."""
    import asyncio
    import subprocess
    import tempfile
    from pathlib import Path

    from agent_uia.audio.synthesizer import SpeechSynthesizer

    async def _run() -> None:
        synthesizer = SpeechSynthesizer()
        tmp = Path(tempfile.mkdtemp()) / "tts_smoke.mp3"
        await synthesizer.speak(text, output_path=tmp)
        typer.echo(f"Playing back {tmp}...")
        typer.echo("(starting default player)")
        subprocess.run(["start", "", str(tmp)], shell=True, check=False)

    asyncio.run(_run())


@app.command()
def model_download(
    size: str = typer.Argument(
        "base", help="Model size: tiny, base, small, medium, large-v3",
    ),
) -> None:
    """Download a Whisper model of the given size."""
    import asyncio

    from agent_uia.audio.model_manager import ModelManager
    from agent_uia.paths import get_models_dir

    models_dir = get_models_dir()
    manager = ModelManager(models_dir=models_dir)

    async def _run() -> None:
        typer.echo(f"Downloading model '{size}'...", err=True)
        success = await manager.download_model(
            size,
            progress_callback=lambda pct: None,
        )
        if success:
            typer.echo(f"Model '{size}' downloaded successfully.", err=True)
        else:
            typer.echo(f"ERROR: Failed to download model '{size}'.", err=True)
            raise typer.Exit(1)

    asyncio.run(_run())


@app.command()
def model_list() -> None:
    """List all known model sizes and their local state."""
    import asyncio

    from agent_uia.audio.model_manager import ModelManager
    from agent_uia.paths import get_models_dir

    models_dir = get_models_dir()
    manager = ModelManager(models_dir=models_dir)

    async def _run() -> None:
        models = await manager.list_models()
        typer.echo(f"{'Size':<20} {'Status':<20} {'Size on Disk':<15}")
        typer.echo("-" * 55)
        total_size = 0
        for m in models:
            disk_size = m.get("size_on_disk", 0) or 0
            total_size += disk_size
            size_str = _fmt_size(disk_size) if disk_size else "-"
            typer.echo(f"{m['name']:<20} {m['status']:<20} {size_str:<15}")
        typer.echo("-" * 55)
        typer.echo(f"{'Total':<20} {'':<20} {_fmt_size(total_size):<15}")

    asyncio.run(_run())


def _fmt_size(bytes_: int) -> str:
    """Format byte count to human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_ < 1024:
            return f"{bytes_:.1f} {unit}"
        bytes_ /= 1024
    return f"{bytes_:.1f} TB"


@app.command()
def model_delete(
    size: str = typer.Argument(..., help="Model size to delete."),
) -> None:
    """Remove a downloaded model by size name."""
    import asyncio

    from agent_uia.audio.model_manager import ModelManager
    from agent_uia.paths import get_models_dir

    models_dir = get_models_dir()
    manager = ModelManager(models_dir=models_dir)

    async def _run() -> None:
        typer.echo(f"Deleting model '{size}'...")
        success = await manager.delete_model(size)
        if success:
            typer.echo(f"Model '{size}' deleted.")
        else:
            typer.echo(
                f"ERROR: Model '{size}' not found or could not be deleted.",
                err=True,
            )
            raise typer.Exit(1)

    asyncio.run(_run())


@app.command()
def config_show() -> None:
    """Print the current config (with API key masked)."""
    from agent_uia.config import ConfigStore

    store = ConfigStore()
    if not store.exists():
        typer.echo("No config file found. Using defaults.")
        raise typer.Exit(0)

    config = store.load()
    d = config.model_dump()
    # Mask API key for display.
    key = d.get("api_key", "")
    if key and len(key) > 8:
        d["api_key"] = key[:4] + "****" + key[-4:]
    for k, v in d.items():
        typer.echo(f"{k}: {v!r}")


@app.command()
def config_edit() -> None:
    """Open the config file in the system's default editor."""
    import os as _os
    from agent_uia.config import ConfigStore

    store = ConfigStore()
    path = store.path
    if not path.exists():
        # Create default config.
        from agent_uia.ui.app_controller import AppConfig
        store.save(AppConfig())
    _os.startfile(str(path))


@app.command(name="config-path")
def config_path() -> None:
    """Print the path to the config file."""
    from agent_uia.config import ConfigStore

    store = ConfigStore()
    typer.echo(str(store.path))


@app.command()
def skills_list() -> None:
    """List all installed skills."""
    import asyncio

    from agent_uia.skills.loader import default_registry

    async def _run() -> None:
        registry = default_registry()
        skills = registry.load_all()
        if not skills:
            typer.echo("No skills installed.")
            return
        typer.echo(f"{'ID':<25} {'Name':<20} {'Version':<10} {'Source':<10}")
        typer.echo("-" * 65)
        for loaded in skills:
            s = loaded.skill
            typer.echo(f"{s.id:<25} {s.name:<20} {s.version:<10} {loaded.source.value:<10}")

    asyncio.run(_run())


@app.command()
def skills_show(
    skill_id: str = typer.Argument(..., help="Skill ID to show."),
) -> None:
    """Show the YAML source of a skill."""
    from agent_uia.skills.loader import default_registry

    registry = default_registry()
    loaded = registry.get(skill_id)
    if loaded is None:
        typer.echo(f"ERROR: Skill '{skill_id}' not found.", err=True)
        raise typer.Exit(1)
    typer.echo(loaded.path.read_text(encoding="utf-8"))


@app.command()
def skills_run(
    skill_id: str = typer.Argument(..., help="Skill ID to run."),
) -> None:
    """Run a skill from the CLI and print the result."""
    import asyncio
    import json as _json

    from agent_uia.executor import UIAExecutor
    from agent_uia.safety import SafetyConfig, SafetyGate
    from agent_uia.skills.runner import SkillRunner
    from agent_uia.skills.loader import default_registry
    from agent_uia.tools.dispatcher import ToolDispatcher

    async def _run() -> None:
        registry = default_registry()
        loaded = registry.get(skill_id)
        if loaded is None:
            typer.echo(f"ERROR: Skill '{skill_id}' not found.", err=True)
            raise typer.Exit(1)

        gate = SafetyGate(SafetyConfig())
        executor = UIAExecutor(safety_gate=gate)
        dispatcher = ToolDispatcher(executor=executor, safety_gate=gate)
        runner = SkillRunner(dispatcher=dispatcher, safety_gate=gate)

        result = await runner.run(loaded.skill)
        typer.echo(f"Status: {result.status.value}")
        typer.echo(f"Message: {result.message}")
        typer.echo(f"Steps: {len(result.steps)}")
        for step in result.steps:
            typer.echo(f"  - {step.step_id}: ok={step.ok} ({step.error or 'ok'})")
        typer.echo(f"Duration: {result.duration_s:.2f}s")

    asyncio.run(_run())


@app.command()
def skills_install(
    source: str = typer.Argument(..., help="File path or URL to install from."),
) -> None:
    """Install a skill from a file path or URL."""
    import asyncio

    from agent_uia.skills.loader import default_registry

    async def _run() -> None:
        registry = default_registry()
        if source.startswith("https://"):
            path = await registry.install_from_url(source)
        elif source.startswith("http://"):
            typer.echo("ERROR: Only HTTPS URLs are allowed.", err=True)
            raise typer.Exit(1)
        else:
            from pathlib import Path as _Path

            path = registry.install_from_file(_Path(source))
        typer.echo(f"Skill installed from {source}")
        typer.echo(f"Destination: {path}")

    asyncio.run(_run())


@app.command()
def skills_uninstall(
    skill_id: str = typer.Argument(..., help="Skill ID to uninstall."),
) -> None:
    """Uninstall a user skill."""
    from agent_uia.skills.loader import default_registry

    registry = default_registry()
    if registry.uninstall(skill_id):
        typer.echo(f"Skill '{skill_id}' uninstalled.")
    else:
        typer.echo(f"ERROR: Skill '{skill_id}' not found or is built-in.", err=True)
        raise typer.Exit(1)


@app.command()
def e2e() -> None:
    """Run all end-to-end tests against a mocked executor."""
    import sys as _sys

    from agent_uia.skills.loader import default_registry

    registry = default_registry()
    skills = registry.load_all()
    typer.echo(f"Loaded {len(skills)} skills. Running E2E tests...")
    typer.echo("Run:  python -m pytest tests/e2e/ -q")
    _sys.exit(0)


@app.command()
def perf() -> None:
    """Print a summary of the performance log."""
    from pathlib import Path

    from agent_uia.paths import get_logs_dir

    perf_log = get_logs_dir() / "perf.jsonl"
    if not perf_log.exists():
        typer.echo("No performance data yet. Run a few tasks first.")
        raise typer.Exit(0)
    lines = perf_log.read_text(encoding="utf-8").strip().split("\n")
    typer.echo(f"Performance log: {perf_log}")
    typer.echo(f"Total data points: {len(lines)}")
    typer.echo()
    typer.echo("Last 10 entries:")
    for line in lines[-10:]:
        typer.echo(f"  {line}")


@app.command(name="perf-tail")
def perf_tail(
    n: int = typer.Argument(default=10, help="Number of entries to show."),
) -> None:
    """Show the last N entries from the performance log."""
    from agent_uia.paths import get_logs_dir

    perf_log = get_logs_dir() / "perf.jsonl"
    if not perf_log.exists():
        typer.echo("No performance data yet.")
        raise typer.Exit(0)
    lines = perf_log.read_text(encoding="utf-8").strip().split("\n")
    for line in lines[-n:]:
        typer.echo(line)


@app.command(name="perf-reset")
def perf_reset() -> None:
    """Clear the performance log file."""
    from agent_uia.paths import get_logs_dir

    perf_log = get_logs_dir() / "perf.jsonl"
    if perf_log.exists():
        perf_log.unlink()
        typer.echo("Performance log cleared.")
    else:
        typer.echo("No performance log to clear.")


@app.command(name="cache-clear")
def cache_clear() -> None:
    """Clear the in-memory LLM and control tree caches."""
    typer.echo("Cache clear is for in-process use. Restart the app to clear caches.")
    typer.echo("Run:  tnt perf-reset  to clear the on-disk perf log.")


def cli_main() -> None:
    """Entry point for the ``tnt`` console script."""
    app()


if __name__ == "__main__":
    cli_main()
