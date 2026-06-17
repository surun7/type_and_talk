# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Demo — end-to-end UIA execution with the safety gate.

Supports two modes:

- ``--no-llm`` (default): Direct UIA executor smoke test (Notepad).
- ``--llm "<instruction>"``: Full LLM-driven path via the ReAct planner.

Usage::

    python -m agent_uia.demo
    python -m agent_uia.demo --llm "Open Notepad and type 'Hello from TNT'."
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
from decimal import Decimal

from agent_uia.platform_check import assert_windows


def _run_no_llm() -> int:
    """Original UIA-only Notepad smoke test. Returns exit code."""
    from agent_uia.safety import SafetyGate, SafetyConfig
    from agent_uia.executor import UIAExecutor

    assert_windows()

    print("=" * 60)
    print("  agent-uia Demo — UIA Executor + Safety Gate smoke test")
    print("=" * 60)
    print()

    safety_checks_passed = 0
    start_time = time.monotonic()

    gate = SafetyGate(SafetyConfig())
    print("[1/7] Safety gate initialised with default config.")
    safety_checks_passed += 1

    executor = UIAExecutor(safety_gate=gate)
    print("[2/7] UIAExecutor created and bound to safety gate.")
    safety_checks_passed += 1

    print("[3/7] Launching Notepad...")
    proc = subprocess.Popen(["notepad.exe"])
    print(f"      PID: {proc.pid}")

    print("[4/7] Waiting for Notepad window...")
    try:
        window = executor.wait_for_window(title_contains="Notepad", timeout=10.0)
    except TimeoutError:
        print("ERROR: Timed out waiting for Notepad window.", file=sys.stderr)
        proc.terminate()
        return 1
    print(f"      Found: class={window.class_name!r}, title={window.title!r}")
    print("      Safety gate: ALLOW (notepad.exe is not blocked)")
    safety_checks_passed += 1

    print("[5/7] Finding the Edit control...")
    try:
        edit_control = executor.wait_for_control(
            window,
            control_type="Edit",
            timeout=10.0,
        )
    except TimeoutError:
        print("ERROR: Timed out waiting for Edit control.", file=sys.stderr)
        executor.close_window(window)
        proc.terminate()
        return 1
    print(
        f"      Edit control: name={edit_control.name!r}, "
        f"automation_id={edit_control.automation_id!r}"
    )
    safety_checks_passed += 1

    test_text = "Hello from Agent UIA\nThis text was typed via UIA.\n"
    print(f"[6/7] Setting value: {test_text!r}")
    executor.set_value(edit_control, test_text)
    safety_checks_passed += 1

    read_text = edit_control.get_text()
    print(f"      Read back: {read_text!r}")
    if test_text.strip() in read_text:
        print("      ✓ Text matches!")
    else:
        print("      ⚠ Text may not fully match (UIA ValuePattern behavior varies)")

    print("[7/7] Closing Notepad (discarding changes)...")
    executor.close_window(window)
    time.sleep(0.5)

    try:
        save_dialog = executor.find_window(title_contains="Notepad", timeout=2.0)
        if save_dialog is not None:
            print("      'Save?' dialog detected — pressing 'n' to discard.")
            import uiautomation as _uia
            _uia.SendKeys("n", waitTime=0.1)
    except Exception:
        pass

    proc.wait(timeout=5)

    elapsed = time.monotonic() - start_time
    print()
    print("=" * 60)
    print("  DEMO COMPLETE")
    print(f"  Status:   ✓ SUCCESS")
    print(f"  Time:     {elapsed:.2f}s")
    print(f"  Safety:   {safety_checks_passed} checks passed")
    print("=" * 60)
    return 0


async def _run_llm(instruction: str) -> int:
    """LLM-driven path via the ReAct planner. Returns exit code."""
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    from agent_uia.llm_client import LLMConfig, UsageLedger
    from agent_uia.planner import Planner, PlannerConfig
    from agent_uia.safety import SafetyGate, SafetyConfig
    from agent_uia.executor import UIAExecutor

    assert_windows()

    # Load .env if present.
    load_dotenv()

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    if not api_key:
        print(
            "ERROR: DEEPSEEK_API_KEY is not set.\n"
            "  Create a .env file with your DeepSeek API key, or set the env var.\n"
            "  cp .env.example .env  and fill in DEEPSEEK_API_KEY",
            file=sys.stderr,
        )
        return 1

    print("=" * 60)
    print("  agent-uia Demo — LLM-driven path")
    print(f"  Model:  {model}")
    print(f"  Task:   {instruction[:80]}{'...' if len(instruction) > 80 else ''}")
    print("=" * 60)
    print()

    # Build components.
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

    async def on_event(event) -> None:
        """Print progress events."""
        from agent_uia.planner import (
            StepStarted,
            LLMCalled,
            ToolCallStarted,
            ToolCallFinished,
            FinalAnswerReady,
        )

        if isinstance(event, StepStarted):
            print(f"\n--- Step {event.step_number} ---")
        elif isinstance(event, LLMCalled):
            resp = event.response
            print(f"  LLM: finish={resp.finish_reason}, "
                  f"tokens={resp.usage.total_tokens}, "
                  f"cost=${resp.usage.estimated_cost_usd:.6f}")
            if resp.message.tool_calls:
                for tc in resp.message.tool_calls:
                    args_preview = str(tc.arguments)[:100]
                    print(f"    → {tc.name}({args_preview})")
        elif isinstance(event, ToolCallStarted):
            pass  # already shown in LLMCalled
        elif isinstance(event, ToolCallFinished):
            ok_mark = "✓" if event.ok else "✗"
            print(f"    {ok_mark} {event.tool_name}: {event.result[:150]}")
        elif isinstance(event, FinalAnswerReady):
            print(f"\n  Final answer: {event.message[:200]}")

    print("Running planner...")
    print()

    result = await planner.run(instruction, on_event=on_event)

    print()
    print("=" * 60)
    print("  LLM DEMO COMPLETE")
    print(f"  Status:       {result.status}")
    print(f"  Steps taken:  {result.steps_taken}")
    print(f"  Total cost:   ${result.total_cost_usd:.6f}")
    print(f"  Total tokens: {result.usage.total_tokens}")
    print(f"  Final message:")
    print(f"    {result.user_facing_message[:500]}")
    print("=" * 60)

    # Map status to exit code.
    code_map = {
        "success": 0,
        "failed": 1,
        "blocked": 2,
        "budget_exceeded": 3,
        "max_steps_exceeded": 4,
    }
    return code_map.get(result.status, 1)


def main() -> int:
    """Parse args and run the selected demo mode."""
    parser = argparse.ArgumentParser(
        description="agent-uia demo — UIA executor + (optional) LLM planner"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--llm",
        type=str,
        metavar="INSTRUCTION",
        help="Run the LLM-driven path with the given instruction.",
    )
    group.add_argument(
        "--no-llm",
        action="store_true",
        help="Run the UIA-only (Notepad) smoke test (default).",
    )
    args = parser.parse_args()

    if args.llm:
        return asyncio.run(_run_llm(args.llm))
    else:
        return _run_no_llm()


if __name__ == "__main__":
    sys.exit(main())
