# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""CLI entry point — ``tnt`` command.

Subcommands:

- ``tnt run "<instruction>"`` — run the planner once.
- ``tnt chat`` — interactive REPL (placeholder).
- ``tnt demo`` — alias for ``python -m agent_uia.demo``.
- ``tnt doctor`` — run safety + executor self-test (no LLM).
- ``tnt --version`` — print version.
"""

from __future__ import annotations

import sys

import typer

from agent_uia import __version__

app = typer.Typer(
    name="tnt",
    help="Type and Talk (TNT) — Windows UIA desktop agent.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        print(f"tnt {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Print version and exit.",
    ),
) -> None:
    pass


@app.command()
def run(
    instruction: str = typer.Argument(..., help="Natural-language instruction to execute."),
) -> None:
    """Execute a single instruction via the LLM planner."""
    import asyncio
    import os
    from decimal import Decimal
    from pathlib import Path

    from dotenv import load_dotenv

    from agent_uia.platform_check import assert_windows
    from agent_uia.llm_client import LLMConfig, UsageLedger
    from agent_uia.planner import Planner, PlannerConfig
    from agent_uia.safety import SafetyGate, SafetyConfig
    from agent_uia.executor import UIAExecutor

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
        system_prompt_file=Path("src/agent_uia/prompts/system_prompt.md"),
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
    """Start an interactive REPL (not yet implemented)."""
    typer.echo("Interactive chat mode is not yet implemented.")
    typer.echo("Use 'tnt run \"<instruction>\"' for single-shot execution.")
    typer.echo("Full REPL coming in Prompt 3.")


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
    import time
    import subprocess

    from agent_uia.platform_check import assert_windows
    from agent_uia.safety import SafetyGate, SafetyConfig
    from agent_uia.executor import UIAExecutor

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


def cli_main() -> None:
    """Entry point for the ``tnt`` console script."""
    app()


if __name__ == "__main__":
    cli_main()
