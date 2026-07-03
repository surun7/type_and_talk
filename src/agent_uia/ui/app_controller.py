# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Glue layer: ties the GUI (tray, floating window, hotkey) to the async Planner.

Uses ``qasync`` to bridge Qt's event loop with asyncio — both run on the same
thread, so signals can be emitted directly from async callbacks.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from decimal import Decimal
from typing import Any, Literal

# Pre-import pydantic (and its fields module) before PySide6 to avoid a
# circular-import interaction between PySide6's shiboken signature loader
# and pydantic's lazy module loading on Python 3.14.
import pydantic  # noqa: F401
from loguru import logger
from pydantic import BaseModel, Field  # noqa: F401
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication

from agent_uia.config import ConfigStore
from agent_uia.executor import UIAExecutor
from agent_uia.llm_client import LLMConfig, UsageLedger
from agent_uia.paths import PACKAGE_DIR, get_logs_dir, get_models_dir, get_model_path
from agent_uia.planner import (
    FinalAnswerReady,
    LLMCalled,
    Planner,
    PlannerConfig,
    StepStarted,
    ToolCallFinished,
    ToolCallStarted,
)
from agent_uia.safety import SafetyConfig, SafetyGate
from agent_uia.ui.theme import Theme, ThemeManager

# Lazy-import UI components to avoid circular imports at module level.
# They are imported inside methods that reference them.

__all__ = [
    "AppConfig",
    "AppController",
    "default_monitor",
    "ControlTreeCache",
    "LLMResponseCache",
    "PerformanceMonitor",
]


# ── performance monitoring ────────────────────────────────────────────────────


class PerformanceMonitor:
    """In-memory performance metrics collector.

    Records durations for LLM calls, tool actions, and full tasks.
    Exposes a ``summary()`` dict consumed by ``PerformanceTab``.
    """

    def __init__(self) -> None:
        self._llm_calls: list[float] = []       # durations in seconds
        self._llm_cache_hits: list[float] = []   # durations in seconds
        self._tool_actions: list[float] = []     # durations in seconds
        self._task_durations: list[float] = []   # durations in seconds
        self._task_steps: list[int] = []
        self._call_history: list[dict] = []      # {hour, count}
        self._events: list[dict] = []            # {timestamp, metric, value, tags}
        self._memory_samples: list[float] = []

    def record_llm_call(self, duration_s: float, cache_hit: bool = False) -> None:
        if cache_hit:
            self._llm_cache_hits.append(duration_s)
        else:
            self._llm_calls.append(duration_s)
        self._events.append({
            "timestamp": time.time(),
            "metric": "llm_call",
            "value": round(duration_s, 4),
            "tags": "cache_hit" if cache_hit else "",
        })

    def record_tool_action(self, duration_s: float) -> None:
        self._tool_actions.append(duration_s)
        self._events.append({
            "timestamp": time.time(),
            "metric": "tool_action",
            "value": round(duration_s, 4),
            "tags": "",
        })

    def record_task(self, duration_s: float, steps: int) -> None:
        self._task_durations.append(duration_s)
        self._task_steps.append(steps)
        self._events.append({
            "timestamp": time.time(),
            "metric": "task",
            "value": round(duration_s, 4),
            "tags": f"steps={steps}",
        })

    def record_memory(self, mb: float) -> None:
        self._memory_samples.append(mb)

    def flush_to_disk(self) -> None:
        """Persist current metrics to a JSON lines file (no-op for now)."""
        # TODO: implement disk persistence
        pass

    def summary(self) -> dict:
        """Return a snapshot dict consumable by ``PerformanceTab``."""
        now = time.time()
        # Hourly buckets for the last 24h.
        buckets: dict[str, int] = {}
        for ev in self._events:
            if ev["metric"] == "llm_call":
                hour_key = time.strftime(
                    "%Y-%m-%dT%H:00", time.localtime(ev["timestamp"])
                )
                buckets[hour_key] = buckets.get(hour_key, 0) + 1
        llm_calls_over_time = [
            {"hour": k, "count": v}
            for k, v in sorted(buckets.items())
        ][-24:]

        def _p(val: float, seq: list) -> float:
            if not seq:
                return 0.0
            import statistics
            sorted_seq = sorted(seq)
            idx = int(len(sorted_seq) * val / 100)
            return sorted_seq[min(idx, len(sorted_seq) - 1)]

        # Phase latencies: p50/p95/p99 for each phase.
        phase_latencies = {}
        if self._llm_calls:
            phase_latencies["llm_call"] = {
                "p50": _p(50, self._llm_calls),
                "p95": _p(95, self._llm_calls),
                "p99": _p(99, self._llm_calls),
            }
        if self._tool_actions:
            phase_latencies["tool_action"] = {
                "p50": _p(50, self._tool_actions),
                "p95": _p(95, self._tool_actions),
                "p99": _p(99, self._tool_actions),
            }

        avg_llm = (
            statistics.mean(self._llm_calls) if self._llm_calls else 0.0
        )
        avg_cache = (
            statistics.mean(self._llm_cache_hits) if self._llm_cache_hits else 0.0
        )
        avg_tool = (
            statistics.mean(self._tool_actions) if self._tool_actions else 0.0
        )
        avg_task_s = (
            statistics.mean(self._task_durations) if self._task_durations else 0.0
        )
        avg_task_steps = (
            round(statistics.mean(self._task_steps)) if self._task_steps else 0
        )
        mem_mb = (
            statistics.mean(self._memory_samples) if self._memory_samples else 0.0
        )

        return {
            "avg_llm_call_ms": avg_llm,
            "avg_llm_call_cache_hit_ms": avg_cache * 1000 if avg_cache else 0,
            "avg_tool_action_ms": avg_tool * 1000,
            "avg_task_duration_s": avg_task_s,
            "avg_task_steps": avg_task_steps,
            "memory_mb": mem_mb,
            "phase_latencies": phase_latencies,
            "llm_calls_over_time": llm_calls_over_time,
            "events": self._events[-50:],
        }


_monitor_instance: PerformanceMonitor | None = None


def default_monitor() -> PerformanceMonitor:
    """Return the global ``PerformanceMonitor`` singleton."""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = PerformanceMonitor()
    return _monitor_instance


# ── response caches ───────────────────────────────────────────────────────────


class ControlTreeCache:
    """Simple TTL cache for UI Automation control tree snapshots."""

    def __init__(self, enabled: bool = True, ttl_s: float = 3.0) -> None:
        self._enabled = enabled
        self._ttl_s = ttl_s
        self._cache: dict[str, tuple[float, object]] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def get(self, key: str) -> object | None:
        if not self._enabled:
            return None
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.time() - ts > self._ttl_s:
            del self._cache[key]
            return None
        return value

    def set(self, key: str, value: object) -> None:
        if self._enabled:
            self._cache[key] = (time.time(), value)

    def clear(self) -> None:
        self._cache.clear()


class LLMResponseCache:
    """Simple TTL cache for LLM responses to avoid redundant API calls."""

    def __init__(self, enabled: bool = True, ttl_s: float = 300.0) -> None:
        self._enabled = enabled
        self._ttl_s = ttl_s
        self._cache: dict[str, tuple[float, str]] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def get(self, key: str) -> str | None:
        if not self._enabled:
            return None
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.time() - ts > self._ttl_s:
            del self._cache[key]
            return None
        return value

    def set(self, key: str, value: str) -> None:
        if self._enabled:
            self._cache[key] = (time.time(), value)

    def clear(self) -> None:
        self._cache.clear()


# ── config ───────────────────────────────────────────────────────────────────


class AppConfig(BaseModel):
    """User-facing configuration for the TNT GUI.

    Loaded from ``~/.tnt/config.json`` (future) — for now, defaults suffice.
    """

    model_config = {"frozen": True}

    # ── Window / UI ────────────────────────────────────────────────────────

    hotkey: str = "ctrl+shift+space"
    main_window_hotkey: str = "ctrl+shift+m"
    floating_window_hide_policy: Literal["never", "on_success", "always_after_5s"] = (
        "on_success"
    )
    auto_hide_delay_s: float = 5.0
    theme: Literal["dark", "light"] = "dark"

    # ── ASR model ──────────────────────────────────────────────────────────

    asr_model: Literal["tiny", "base", "small", "medium", "large-v3"] = "base"
    download_mirror: str = "https://huggingface.co"
    voice_opted_out: bool = False
    first_run_completed: bool = False

    # ── Push-to-talk ───────────────────────────────────────────────────────

    ptt_hotkey: str = "ctrl+shift+v"
    ptt_release_silence_timeout_s: float = 1.5
    ptt_max_duration_s: float = 60.0

    # ── Text-to-speech ─────────────────────────────────────────────────────

    enable_tts: bool = False
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_rate: str = "+0%"

    # ── Performance / caching ──────────────────────────────────────────────

    llm_cache_enabled: bool = True
    llm_cache_ttl_s: float = 300.0
    control_tree_cache_enabled: bool = True
    control_tree_cache_ttl_s: float = 3.0
    perf_flush_interval_s: float = 30.0
    enable_perf_monitoring: bool = True


# ── Model provider adapter ───────────────────────────────────────────────────


class _ModelProvider:
    """Adapter that bridges ``ModelManager`` to ``SpeechRecognizer.get_model()``.

    ``SpeechRecognizer`` expects its ``model_manager`` argument to expose a
    ``get_model(model_size, device, compute_type)`` callable.  This adapter
    satisfies that contract by loading a ``faster-whisper.WhisperModel`` from
    the local cache path that ``ModelManager`` has already downloaded.
    """

    def __init__(self, model_manager: Any) -> None:
        self._model_manager = model_manager

    def get_model(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "int8",
    ) -> Any:
        """Load and return a ``faster_whisper.WhisperModel`` instance.

        Args:
            model_size: One of ``"tiny"``, ``"base"``, ``"small"``,
                ``"medium"``, ``"large-v3"``.
            device: Torch device string (``"auto"``, ``"cpu"``, ``"cuda"``).
            compute_type: Compute type (``"int8"``, ``"float16"``, etc.).

        Returns:
            A ``faster_whisper.WhisperModel`` loaded from the local cache.
        """
        # Import here so the dependency is only required when voice is used.
        from faster_whisper import WhisperModel

        model_path = get_model_path(model_size)
        return WhisperModel(
            str(model_path),
            device=device,
            compute_type=compute_type,
        )


# ── AppController ────────────────────────────────────────────────────────────


class AppController(QObject):
    """Top-level controller that wires UI components to the async Planner.

    Signals (all thread-safe since Qt + asyncio share one thread via qasync):
        status_changed: Status bar text update.
        tool_event: One-liner describing a tool call (dimmed in UI).
        final_answer_ready: The Planner's final answer.
        task_finished: Outcome — ``"success"`` | ``"failed"`` | ``"blocked"``
            | ``"budget"`` | ``"max_steps"``.
        paused_changed: Whether the agent is paused.
    """

    # ── existing signals ────────────────────────────────────────────────────

    status_changed = Signal(str)
    tool_event = Signal(str)
    final_answer_ready = Signal(str)
    task_finished = Signal(str)
    paused_changed = Signal(bool)

    # ── voice pipeline signals ──────────────────────────────────────────────

    model_status_changed = Signal(str, str)  # model_size, state_name
    model_download_progress = Signal(str, float, int, int)  # size, percent, downloaded, total
    recording_started = Signal()
    recording_stopped = Signal()
    transcription_ready = Signal(str)
    transcription_failed = Signal(str)
    tts_started = Signal()
    tts_finished = Signal()

    def __init__(
        self,
        config: AppConfig | None = None,
    ) -> None:
        super().__init__()
        self._config = config or AppConfig()
        self._paused = False
        self._app: QApplication | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tray: Any = None
        self._floating: Any = None
        self._hotkey: Any = None
        self._planner: Planner | None = None
        self._ledger: UsageLedger | None = None
        self._quit_requested = False
        self._config_store: ConfigStore | None = None
        self._main_window: Any = None

        # Lazy-built core components.
        self._llm_config: LLMConfig | None = None
        self._safety_gate: SafetyGate | None = None
        self._executor: UIAExecutor | None = None

        # History path.
        self._history_dir = get_logs_dir()
        self._history_path = self._history_dir / "history.jsonl"

        # Performance monitoring & caching (populated in start()).
        self._perf_flush_task: asyncio.Task | None = None
        self._control_tree_cache: ControlTreeCache | None = None
        self._llm_cache: LLMResponseCache | None = None

        # ── voice pipeline (lazy-built) ────────────────────────────────────

        self._hotkey_group: Any = None
        self._model_manager: Any = None
        self._recognizer: Any = None
        self._recorder: Any = None
        self._silence_detector: Any = None
        self._synthesizer: Any = None
        self._ptt_hotkey: Any = None
        self._recording = False

    # ── properties ───────────────────────────────────────────────────────

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool) -> None:
        if self._paused != value:
            self._paused = value
            self.paused_changed.emit(value)
            if self._tray is not None:
                from agent_uia.ui.tray import State

                if self._tray is not None:
                    self._tray.set_state(State.PAUSED if value else State.IDLE)

    @property
    def config(self) -> AppConfig:
        return self._config

    # ── start (blocking — enters the Qt event loop) ──────────────────────

    def start(self) -> None:
        """Create the GUI, wire everything, and enter the Qt event loop.

        Call exactly once. Blocks until ``quit()`` is called.
        """
        # 1. Build QApplication with high-DPI support.
        self._app = QApplication.instance() or QApplication(sys.argv)
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)   # type: ignore[attr-defined]
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)      # type: ignore[attr-defined]

        # 2. Install qasync event loop (merges Qt + asyncio).
        import qasync

        self._loop = qasync.QEventLoop(self._app)
        asyncio.set_event_loop(self._loop)

        # 3. Load core async dependencies (LLM, safety, executor).
        self._init_core()

        # 3b. Initialise performance monitoring and caches.
        self._init_performance_infra()

        # 4. Build UI components.
        self._init_ui()

        # Load persisted config.
        self._config_store = ConfigStore()
        if self._config_store.exists():
            try:
                self._config = self._config_store.load()
            except Exception:
                self._config = self._config or AppConfig()

        # 4b. Pre-warm floating window and main window (create but don't show).
        self._pre_warm_windows()

        # Apply theme.
        ThemeManager.apply_to(self._app, Theme.DARK if self._config.theme == "dark" else Theme.LIGHT)

        # 5. Build audio components and register hotkeys.
        self._init_audio()

        # 6. Show first-run dialog (modal, blocks until dismissed).
        self._handle_first_run()

        # 7. Show tray.
        self._tray.show()

        # 8. Start background perf flush loop.
        if self._config.enable_perf_monitoring and self._loop is not None:
            self._perf_flush_task = asyncio.ensure_future(
                self._perf_flush_loop(),
                loop=self._loop,
            )

        # 9. Enter event loop (blocking).
        logger.info("TNT GUI started.")
        self._loop.run_forever()
        logger.info("TNT GUI stopped.")

    # ── audio initialisation ────────────────────────────────────────────────

    def _init_audio(self) -> None:
        """Build the audio pipeline: model manager, recorder, hotkeys.

        Call this **after** ``_init_ui()`` so the floating window exists for
        status updates.
        """
        # ── ModelManager (always available for downloads) ──────────────────
        try:
            from agent_uia.audio.model_manager import ModelManager

            self._model_manager = ModelManager(
                models_dir=get_models_dir(),
                mirror=self._config.download_mirror,
            )
        except ImportError as exc:
            logger.warning("ModelManager not available: %s", exc)
            self._model_manager = None

        # ── Lazy audio components (only when voice is opted in) ────────────
        if (
            not self._config.voice_opted_out
            and self._config.first_run_completed
            and self._model_manager is not None
        ):
            self._init_lazy_audio()

        # ── Hotkey group (replaces old single-hotkey registration) ─────────
        from agent_uia.ui.hotkey import GlobalHotkeyGroup

        self._hotkey_group = GlobalHotkeyGroup()
        self._hotkey_group.add(
            self._config.hotkey, self.toggle_floating_window
        )
        if not self._config.voice_opted_out:
            self._ptt_hotkey = self._hotkey_group.add(
                self._config.ptt_hotkey, self._on_ptt_press
            )
        self._hotkey_group.add(self._config.main_window_hotkey, self.toggle_main_window)
        self._hotkey_group.start()

        # ── Wire TTS to final answer signal ───────────────────────────────
        # (synthesizer is lazily created inside the handler)
        self.final_answer_ready.connect(self._on_final_answer_tts)

    def _init_lazy_audio(self) -> None:
        """Lazily build recognizer, recorder, silence detector, synthesizer.

        Each component is wrapped in a ``try``/``except ImportError`` so the
        application works gracefully when optional audio dependencies are
        missing.
        """
        # SpeechRecognizer (lazy — model loads on first transcribe).
        try:
            from agent_uia.audio.recognizer import SpeechRecognizer

            self._recognizer = SpeechRecognizer(
                model_manager=_ModelProvider(self._model_manager),
                model_size=self._config.asr_model,
            )
        except ImportError as exc:
            logger.warning("SpeechRecognizer not available: %s", exc)
            self._recognizer = None

        # AudioRecorder.
        try:
            from agent_uia.audio.recorder import AudioRecorder

            self._recorder = AudioRecorder()
        except ImportError as exc:
            logger.warning("AudioRecorder not available: %s", exc)
            self._recorder = None

        # SilenceDetector.
        try:
            from agent_uia.audio.vad import SilenceDetector

            self._silence_detector = SilenceDetector(
                silence_timeout_s=self._config.ptt_release_silence_timeout_s,
                max_duration_s=self._config.ptt_max_duration_s,
            )
        except ImportError as exc:
            logger.warning("SilenceDetector not available: %s", exc)
            self._silence_detector = None

        # SpeechSynthesizer (TTS, opt-in).
        try:
            from agent_uia.audio.synthesizer import SpeechSynthesizer

            self._synthesizer = SpeechSynthesizer(
                voice=self._config.tts_voice,
                rate=self._config.tts_rate,
            )
        except ImportError as exc:
            logger.warning("SpeechSynthesizer not available: %s", exc)
            self._synthesizer = None

    def _handle_first_run(self) -> None:
        """Show the first-run dialog if needed and persist the user's choice.

        Runs synchronously (modal) before the event loop starts.  The dialog
        already handles ``"quit"`` internally by calling ``quit()``.
        """
        from agent_uia.ui.first_run_dialog import FirstRunDialog

        result = FirstRunDialog.run_if_needed(None, self)
        if result is None:
            # Already completed — nothing to do.
            return

        choice, model_size, mirror = result

        if choice == "download":
            # Persist the user's choices.
            self._config = self._config.model_copy(
                update={
                    "download_mirror": mirror,
                    "asr_model": model_size,
                    "voice_opted_out": False,
                    "first_run_completed": True,
                }
            )
            # Start the download in the background (non-blocking).
            if self._loop is not None and self._model_manager is not None:
                asyncio.run_coroutine_threadsafe(
                    self._download_model(model_size),
                    self._loop,
                )
            # Initialise lazy audio components now that voice is opted in.
            self._init_lazy_audio()

        elif choice == "text_only":
            self._config = self._config.model_copy(
                update={
                    "voice_opted_out": True,
                    "first_run_completed": True,
                }
            )

        # ``quit`` is already handled by the dialog itself.

    # ── UI-control methods (callable from Qt thread) ─────────────────────

    def show_floating_window(self) -> None:
        if self._floating is not None:
            self._floating.show()
            self._floating.clear_input()
            self._floating.clear_response()
            self._floating.raise_()
            self._floating.activateWindow()

    def hide_floating_window(self) -> None:
        if self._floating is not None:
            self._floating.hide_with_fade()

    def toggle_floating_window(self) -> None:
        if self._floating is None:
            return
        if self._floating.isVisible():
            self.hide_floating_window()
        else:
            self.show_floating_window()

    def toggle_paused(self) -> None:
        self.paused = not self._paused

    def show_main_window(self) -> None:
        """Show the main window (create if first time)."""
        if self._main_window is None:
            from agent_uia.ui.main_window import MainWindow
            self._main_window = MainWindow(
                app_controller=self,
                config=self._config,
                config_store=self._config_store,
            )
        self._main_window.show()
        self._main_window.raise_()
        self._main_window.activateWindow()

    def hide_main_window(self) -> None:
        if self._main_window is not None:
            self._main_window.hide()

    def toggle_main_window(self) -> None:
        if self._main_window is not None and self._main_window.isVisible():
            self.hide_main_window()
        else:
            self.show_main_window()

    async def get_history_paginated(
        self,
        offset: int = 0,
        limit: int = 50,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read history.jsonl in reverse, return a page of entries."""
        import json as _json
        from pathlib import Path as _Path

        path = self._history_path
        if not path.exists():
            return []

        entries: list[dict[str, Any]] = []
        try:
            text = await asyncio.to_thread(_Path.read_text, path, encoding="utf-8")
            lines = text.strip().split("\n")
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    entry = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                # Apply search filter.
                if search:
                    search_lower = search.lower()
                    if (search_lower not in entry.get("user_text", "").lower()
                            and search_lower not in entry.get("final_message", "").lower()):
                        continue
                entries.append(entry)

            return entries[offset:offset + limit]
        except Exception:
            logger.exception("Failed to read history")
            return []

    def quit(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down TNT GUI...")
        self._quit_requested = True

        # Close main window if open.
        if self._main_window is not None:
            self._main_window.close()
            self._main_window = None

        # Unregister all hotkeys.
        if self._hotkey_group is not None:
            self._hotkey_group.stop()
        elif self._hotkey is not None:
            self._hotkey.stop()

        # Stop any active recording.
        self._recording = False

        # Stop TTS playback if active.
        if self._synthesizer is not None:
            try:
                self._synthesizer.stop()
            except Exception:
                pass

        # Cancel perf flush background task.
        if self._perf_flush_task is not None:
            self._perf_flush_task.cancel()
            self._perf_flush_task = None

        # Flush performance monitor one last time.
        try:
            default_monitor().flush_to_disk()
        except Exception:
            pass

        # Clear response caches.
        if self._control_tree_cache is not None:
            self._control_tree_cache.clear()
        if self._llm_cache is not None:
            self._llm_cache.clear()

        # Stop the event loop (quits the application).
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._app is not None:
            self._app.quit()

    # ── run_task (async — called from Qt slot) ───────────────────────────

    async def run_task(self, user_text: str) -> None:
        """Execute a user instruction through the Planner.

        Safe to call from Qt signal handlers (creates an asyncio task).
        """
        from agent_uia.ui.tray import State

        if self._paused:
            msg = (
                "Agent is paused. Click 'Pause Agent' in the tray menu "
                "to resume."
            )
            self.final_answer_ready.emit(msg)
            self.status_changed.emit("Paused")
            return

        if self._planner is None:
            msg = "LLM not configured. Set DEEPSEEK_API_KEY in .env and restart."
            self.final_answer_ready.emit(msg)
            self.status_changed.emit("Error")
            if self._tray is not None:
                self._tray.set_state(State.ERROR)
            return

        # Update UI state.
        if self._tray is not None:
            self._tray.set_state(State.THINKING)
        self.status_changed.emit("Thinking...")
        if self._floating is not None:
            self._floating.set_task_running(True)
            self._floating.clear_response()
            self._floating.clear_input()

        task_id = str(uuid.uuid4())[:8]

        try:
            result = await self._planner.run(
                user_text,
                on_event=self._on_planner_event,
                task_id=task_id,
            )

            # Map status.
            status_map = {
                "success": "success",
                "failed": "failed",
                "blocked": "blocked",
                "budget_exceeded": "budget",
                "max_steps_exceeded": "max_steps",
            }
            mapped = status_map.get(result.status, "failed")
            self.task_finished.emit(mapped)
            self.status_changed.emit(
                f"Done in {result.steps_taken} step{'s' if result.steps_taken != 1 else ''}"
                f" · ${result.total_cost_usd:.4f}"
            )
            if self._tray is not None:
                self._tray.set_state(State.IDLE)

            # Persist history (via thread-pool to avoid blocking the loop).
            await self._append_history(
                task_id=task_id,
                user_text=user_text,
                status=result.status,
                final_message=result.user_facing_message,
                cost_usd=str(result.total_cost_usd),
                steps=result.steps_taken,
            )

            # Auto-hide logic.
            if self._config.floating_window_hide_policy == "always_after_5s":
                QTimer.singleShot(
                    int(self._config.auto_hide_delay_s * 1000),
                    self.hide_floating_window,
                )
            elif (
                self._config.floating_window_hide_policy == "on_success"
                and result.status == "success"
            ):
                self.hide_floating_window()

        except Exception as exc:
            logger.exception("Task failed unexpectedly")
            self.task_finished.emit("failed")
            self.status_changed.emit("Error")
            self.final_answer_ready.emit(f"Task failed: {exc}")
            if self._tray is not None:
                self._tray.set_state(State.ERROR)

        finally:
            if self._floating is not None:
                self._floating.set_task_running(False)

    # ── skill execution ──────────────────────────────────────────────────

    async def run_skill(
        self,
        skill_id: str,
        inputs: dict[str, Any] | None = None,
    ) -> None:
        """Execute a skill by ID via the SkillRunner.

        Results are written to history and surfaced in the FloatingWindow.
        """
        from agent_uia.skills.loader import default_registry
        from agent_uia.skills.runner import SkillRunner

        if self._tray is not None:
            from agent_uia.ui.tray import State
            self._tray.set_state(State.THINKING)

        self.status_changed.emit(f"Running skill: {skill_id}")

        try:
            registry = default_registry()
            loaded = registry.get(skill_id)
            if loaded is None:
                self.final_answer_ready.emit(f"Skill '{skill_id}' not found.")
                self.status_changed.emit("Error")
                return

            from agent_uia.tools.dispatcher import ToolDispatcher

            dispatcher = ToolDispatcher(
                executor=self._executor,
                safety_gate=self._safety_gate,
                app_controller=self,
            )
            runner = SkillRunner(
                dispatcher=dispatcher,
                safety_gate=self._safety_gate,
                app_controller=self,
            )

            async def _on_event(event):
                from agent_uia.skills.runner import StepStarted, StepFinished
                if isinstance(event, StepStarted):
                    self.status_changed.emit(f"Skill step: {event.step_name}")
                elif isinstance(event, StepFinished):
                    status = "✓" if event.ok else "✗"
                    self.status_changed.emit(f"  {status} {event.step_id}")

            result = await runner.run(loaded.skill, inputs=inputs, on_event=_on_event)

            from agent_uia.skills.runner import SkillStatus
            if result.status == SkillStatus.SUCCESS:
                self.final_answer_ready.emit(result.message)
                self.status_changed.emit(f"Skill '{skill_id}' completed")
            else:
                self.final_answer_ready.emit(
                    f"Skill '{skill_id}' {result.status.value}: {result.message}"
                )
                self.status_changed.emit(f"Skill failed: {result.status.value}")

            # Write to history.
            await self._append_history(
                task_id=f"skill-{skill_id}",
                user_text=f"[skill] {loaded.skill.name}",
                status=result.status.value,
                final_message=result.message,
                cost_usd="0",
                steps=len(result.steps),
            )

        except Exception as exc:
            logger.exception(f"Skill execution failed: {skill_id}")
            self.final_answer_ready.emit(f"Skill failed: {exc}")
            self.status_changed.emit("Error")
        finally:
            if self._tray is not None:
                from agent_uia.ui.tray import State
                self._tray.set_state(State.IDLE)
            if self._floating is not None:
                self._floating.set_task_running(False)

    # ── internal: core init ──────────────────────────────────────────────

    def _init_core(self) -> None:
        """Build LLM config, safety gate, executor, planner."""
        from dotenv import load_dotenv

        load_dotenv()

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            logger.warning(
                "DEEPSEEK_API_KEY not set. GUI will launch, but tasks will "
                "surface a friendly error."
            )

        base_url = os.environ.get(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        )
        model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

        self._llm_config = LLMConfig(
            api_key=api_key,
            base_url=base_url,
            model=model,
        )

        safety_config = SafetyConfig()
        self._safety_gate = SafetyGate(safety_config)
        self._executor = UIAExecutor(safety_gate=self._safety_gate)
        self._ledger = UsageLedger()

        if api_key:
            planner_config = PlannerConfig(
                llm=self._llm_config,
                max_steps=20,
                max_cost_usd_per_task=Decimal("0.10"),
                system_prompt_file=PACKAGE_DIR / "prompts" / "system_prompt.md",
                enable_streaming=False,
            )
            self._planner = Planner(
                config=planner_config,
                executor=self._executor,
                safety_gate=self._safety_gate,
                usage_ledger=self._ledger,
                app_controller=self,
            )

    # ── internal: performance infrastructure ───────────────────────────────

    def _init_performance_infra(self) -> None:
        """Create performance monitor, response caches, and wire them into
        the executor / LLM client.

        Call this **after** :meth:`_init_core` so that the executor and
        planner already exist.
        """
        if not self._config.enable_perf_monitoring:
            return

        # 1. Ensure the global PerformanceMonitor singleton exists.
        default_monitor()

        # 2. Create caches.
        self._control_tree_cache = ControlTreeCache(
            enabled=self._config.control_tree_cache_enabled,
            ttl_s=self._config.control_tree_cache_ttl_s,
        )
        self._llm_cache = LLMResponseCache(
            enabled=self._config.llm_cache_enabled,
            ttl_s=self._config.llm_cache_ttl_s,
        )

        # 3. Wire ControlTreeCache into UIAExecutor (if the executor supports it).
        if self._executor is not None and hasattr(self._executor, "set_cache"):
            self._executor.set_cache(self._control_tree_cache)

        # 4. Wire LLMResponseCache into the planner's LLM client
        #    (if the planner exposes the client).
        if self._planner is not None and hasattr(self._planner, "set_llm_cache"):
            self._planner.set_llm_cache(self._llm_cache)

    def _pre_warm_windows(self) -> None:
        """Create floating and main windows without showing them.

        This reduces perceived latency on the first ``show()`` call because
        widget construction and layout work is done ahead of time.
        """
        # The floating window is already built in _init_ui — just mark it.
        if self._floating is not None:
            self._floating.set_pre_warmed(True)

        # Lazily construct the main window so its creation cost is paid now.
        if self._main_window is None:
            from agent_uia.ui.main_window import MainWindow

            self._main_window = MainWindow(
                app_controller=self,
                config=self._config,
                config_store=self._config_store,
            )
            self._main_window.hide()  # ensure hidden after construction

    # ── internal: perf flush loop ──────────────────────────────────────────

    async def _perf_flush_loop(self) -> None:
        """Background task that periodically flushes performance metrics to disk."""
        interval_s = self._config.perf_flush_interval_s
        while not self._quit_requested:
            await asyncio.sleep(interval_s)
            try:
                default_monitor().flush_to_disk()
            except Exception:  # noqa: BLE001
                logger.warning("Perf flush failed (ignored)")

    # ── internal: history rotation (5 MB threshold) ────────────────────────

    def _rotate_history_if_needed(self) -> None:
        """Rotate history.jsonl if it exceeds 5 MB (keep last 2 files).

        Called before appending each history entry.
        """
        max_bytes = 5 * 1024 * 1024  # 5 MB
        try:
            size = self._history_path.stat().st_size
            if size <= max_bytes:
                return
        except OSError:
            return

        base = self._history_path
        bak1 = base.with_suffix(".jsonl.1")
        bak2 = base.with_suffix(".jsonl.2")
        try:
            if bak1.exists():
                bak2.unlink(missing_ok=True)
                bak1.rename(bak2)
            base.rename(bak1)
        except OSError:
            logger.exception("Failed to rotate history file at 5 MB")

    def _init_ui(self) -> None:
        """Build tray, floating window; wire signals.

        Hotkey registration moved to :meth:`_init_audio` so the window-toggle
        and PTT hotkeys can share a single ``GlobalHotkeyGroup``.
        """
        from agent_uia.ui.floating_window import FloatingWindow
        from agent_uia.ui.tray import TrayIcon

        # Floating window.
        self._floating = FloatingWindow(self)
        self._floating.submit_requested.connect(self._on_submit)

        # Tray icon.
        self._tray = TrayIcon(self)
        self._tray.toggle_window_requested.connect(self.toggle_floating_window)

        # Wire signals.
        self.status_changed.connect(self._on_status_changed)
        self.tool_event.connect(self._on_tool_event)
        self.final_answer_ready.connect(self._on_final_answer)

    # ── internal: signal wiring ──────────────────────────────────────────

    def _on_status_changed(self, text: str) -> None:
        if self._floating is not None:
            self._floating.set_status(text)

    def _on_tool_event(self, text: str) -> None:
        if self._floating is not None:
            self._floating.append_tool_event(text)

    def _on_final_answer(self, text: str) -> None:
        if self._floating is not None:
            self._floating.set_final_answer(text)

    def _on_final_answer_tts(self, text: str) -> None:
        """Optional TTS playback for the final answer.

        Connected to ``final_answer_ready`` in :meth:`_init_audio`.
        Speaks the answer aloud when TTS is enabled and the synthesizer is
        available.
        """
        if not self._config.enable_tts or self._synthesizer is None:
            return
        if not text.strip():
            return
        self.tts_started.emit()
        asyncio.create_task(self._speak_with_signal(text))

    async def _speak_with_signal(self, text: str) -> None:
        """Synthesise speech and emit ``tts_finished`` on completion."""
        try:
            await self._synthesizer.speak(text)
        except Exception as exc:
            logger.warning("TTS playback failed: %s", exc)
        finally:
            self.tts_finished.emit()

    def _on_submit(self, text: str) -> None:
        """Slot: user pressed Enter in the floating window input."""
        asyncio.create_task(self.run_task(text))

    # ── internal: hotkey ─────────────────────────────────────────────────

    def _build_hotkey_callback(self):
        """Return a zero-arg closure that toggles the floating window.

        Retained for compatibility; the ``GlobalHotkeyGroup`` in
        :meth:`_init_audio` now passes ``toggle_floating_window`` directly.
        """
        return self.toggle_floating_window

    # ── confirmation dialog bridge ───────────────────────────────────────

    async def request_user_confirmation(
        self,
        action_type: str,
        target: str,
        risk_explanation: str,
        timeout_s: int = 30,
    ) -> Literal["yes", "no", "stop", "timeout"]:
        """Show a modal confirmation dialog and return the user's choice.

        Runs ``QDialog.exec_()`` on the Qt/asyncio main thread. ``exec_()``
        spins a local event loop so the UI remains responsive while waiting
        for the user.

        Every request and outcome is logged to the safety audit log.
        """
        from agent_uia.ui.confirmation_dialog import ConfirmationDialog

        result = ConfirmationDialog.ask(
            None,
            action_type=action_type,
            target=target,
            risk_explanation=risk_explanation,
            timeout_s=timeout_s,
        )

        # Log to audit.
        if self._safety_gate is not None:
            self._safety_gate._record(
                actor="user",
                action_type="request_user_confirmation",
                target=target,
                verdict=result.upper(),
                reason=f"User responded {result} to action {action_type!r} on {target!r}.",
                user_response=result,
            )
            logger.info(
                "Confirmation for {!r} on {!r}: {}",
                action_type,
                target,
                result,
            )

        return result

    # ── internal: planner event translation ──────────────────────────────

    async def _on_planner_event(self, event: Any) -> None:
        """Translate PlannerEvent to Qt signals."""
        from agent_uia.ui.tray import State

        if isinstance(event, StepStarted):
            self.status_changed.emit(f"Step {event.step_number}")
            if self._tray is not None:
                self._tray.set_state(State.THINKING)

        elif isinstance(event, LLMCalled):
            self.status_changed.emit(
                f"Step {event.step_number} — LLM responded"
            )

        elif isinstance(event, ToolCallStarted):
            args_preview = json.dumps(event.arguments, ensure_ascii=False)
            if len(args_preview) > 80:
                args_preview = args_preview[:77] + "..."
            self.tool_event.emit(
                f"→ {event.tool_name}: {args_preview}"
            )
            self.status_changed.emit(
                f"Step {event.step_number} — {event.tool_name}"
            )

        elif isinstance(event, ToolCallFinished):
            status = "✓" if event.ok else "✗"
            self.tool_event.emit(
                f"  {status} {event.tool_name} — done"
            )

        elif isinstance(event, FinalAnswerReady):
            self.final_answer_ready.emit(event.message)

    # ── internal: history persistence ────────────────────────────────────

    async def _append_history(
        self,
        *,
        task_id: str,
        user_text: str,
        status: str,
        final_message: str,
        cost_usd: str,
        steps: int,
    ) -> None:
        """Append one JSON line to the history file. Rotate at 10 MB.

        Runs I/O on a thread-pool to avoid blocking the event loop.
        """
        entry = {
            "ts": time.time(),
            "task_id": task_id,
            "user_text": user_text,
            "status": status,
            "final_message": final_message,
            "cost_usd": cost_usd,
            "steps": steps,
        }
        await asyncio.to_thread(self._write_history_entry, entry)

    def _write_history_entry(self, entry: dict[str, Any]) -> None:
        """Synchronous I/O helper (runs in thread-pool)."""
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed()
            with open(self._history_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            logger.exception("Failed to write history entry")

    def _rotate_if_needed(self) -> None:
        """Rotate history.jsonl if it exceeds 10 MB (keep last 2 files)."""
        max_bytes = 10 * 1024 * 1024
        try:
            size = self._history_path.stat().st_size
            if size <= max_bytes:
                return
        except OSError:
            return

        base = self._history_path
        # Move .1 → .2, then rename base → .1
        bak1 = base.with_suffix(".jsonl.1")
        bak2 = base.with_suffix(".jsonl.2")
        try:
            if bak1.exists():
                bak2.unlink(missing_ok=True)
                bak1.rename(bak2)
            base.rename(bak1)
        except OSError:
            logger.exception("Failed to rotate history file")

    # ══════════════════════════════════════════════════════════════════════
    #  Voice pipeline — model management
    # ══════════════════════════════════════════════════════════════════════

    async def ensure_model_ready(self, model_size: str | None = None) -> bool:
        """Check whether the requested ASR model is installed and ready.

        If the model is not yet on disk a download is started in the
        background.  If another download is already in progress this method
        waits for it to complete (download coalescing).

        Args:
            model_size: One of ``"tiny"``, ``"base"``, ``"small"``,
                ``"medium"``, ``"large-v3"``.  Defaults to
                ``self._config.asr_model``.

        Returns:
            ``True`` if the model is (or became) ready, ``False`` on failure.
        """
        size = model_size or self._config.asr_model

        if self._model_manager is None:
            logger.error("ModelManager not initialised — cannot check model.")
            return False

        try:
            info = await self._model_manager.get_status(size)
        except ValueError as exc:
            logger.error(str(exc))
            return False

        if info.state.name == "READY":
            return True

        if info.state.name == "DOWNLOADING":
            self.status_changed.emit(f"Voice: waiting for {size} download…")
            # The ModelManager coalesces concurrent downloads, so calling
            # ``download()`` while another task is downloading will wait.
            try:
                await self._model_manager.download(size)
                return True
            except (RuntimeError, ImportError) as exc:
                logger.error("Model download failed: %s", exc)
                self.model_status_changed.emit(size, "failed")
                return False

        # NOT_INSTALLED — start a fresh download.
        return await self._download_model(size)

    async def _download_model(self, model_size: str) -> bool:
        """Download the ASR model and emit progress via Qt signals.

        Args:
            model_size: Model size identifier.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        if self._model_manager is None:
            self.status_changed.emit("Voice: model manager unavailable")
            return False

        self.model_status_changed.emit(model_size, "downloading")
        self.status_changed.emit(f"Voice: downloading {model_size}…")

        def _on_progress(percent: float, downloaded: int, total: int) -> None:
            self.model_download_progress.emit(
                model_size, percent, downloaded, total
            )

        try:
            await self._model_manager.download(
                model_size,
                on_progress=_on_progress,
            )
            self.model_status_changed.emit(model_size, "ready")
            self.status_changed.emit(f"Voice: {model_size} ready")
            return True
        except (RuntimeError, ImportError) as exc:
            logger.error("Failed to download model %s: %s", model_size, exc)
            self.model_status_changed.emit(model_size, "failed")
            self.status_changed.emit(f"Voice: {model_size} download failed")
            return False

    # ══════════════════════════════════════════════════════════════════════
    #  Voice pipeline — push-to-talk
    # ══════════════════════════════════════════════════════════════════════

    def _on_ptt_press(self) -> None:
        """Toggle PTT recording on/off.

        Called from the hotkey pump thread (background thread).  The first
        press starts recording; the second press stops it.  Silence detection
        can also stop recording automatically.
        """
        if self._recording:
            self._on_ptt_release()
            return

        # Guard: model must be installed / downloading.
        if self._model_manager is None:
            self.status_changed.emit("Voice: model manager not available")
            return

        # Ensure the async PTT routine runs on the main event loop.
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._start_ptt(), self._loop)

    async def _start_ptt(self) -> None:
        """Async PTT implementation: record, detect silence, transcribe.

        Uses ``sounddevice`` directly with a custom callback so that every
        audio frame can be fed to the ``SilenceDetector`` in real time.
        Falls back gracefully when audio dependencies are missing.
        """
        # ── Verify model readiness ────────────────────────────────────────
        try:
            info = await self._model_manager.get_status(self._config.asr_model)
            if info.state.name != "READY":
                self.model_status_changed.emit(
                    self._config.asr_model, info.state.value
                )
                self.status_changed.emit(
                    f"Voice: model {info.state.value}"
                )
                return
        except Exception as exc:
            logger.warning("Model status check failed: %s", exc)
            self.status_changed.emit("Voice: model check failed")
            return

        # ── Lazy-import audio dependencies ────────────────────────────────
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as exc:
            self.status_changed.emit(f"Voice: audio capture unavailable ({exc})")
            return

        # Ensure silence detector is ready.
        if self._silence_detector is None:
            try:
                from agent_uia.audio.vad import SilenceDetector

                self._silence_detector = SilenceDetector(
                    silence_timeout_s=self._config.ptt_release_silence_timeout_s,
                    max_duration_s=self._config.ptt_max_duration_s,
                )
            except ImportError as exc:
                self.status_changed.emit(f"Voice: VAD unavailable ({exc})")
                return

        # ── Recording state ────────────────────────────────────────────────
        samplerate = 16000
        channels = 1
        blocksize = 1024  # ~64 ms @ 16 kHz

        buffers: list[np.ndarray] = []
        stop_called = False

        self._silence_detector.reset()
        self._recording = True
        self.recording_started.emit()
        self.status_changed.emit("Listening…")

        def _callback(
            indata: np.ndarray,
            frames: int,  # noqa: ARG001
            _time_info: object,
            status: sd.CallbackFlags,
        ) -> None:
            """sounddevice InputStream callback (audio capture thread)."""
            nonlocal stop_called
            if status:
                return
            if not self._recording:
                stop_called = True
                return

            # Buffer the audio.
            buffers.append(indata.copy())

            # Feed the frame to the silence detector.
            audio_bytes = (indata * 32767).astype(np.int16).tobytes()
            _, should_stop = self._silence_detector.process_frame(audio_bytes)

            if should_stop:
                self._recording = False  # signal the main loop
                stop_called = True

        # ── Start stream ───────────────────────────────────────────────────
        stream = sd.InputStream(
            samplerate=samplerate,
            channels=channels,
            blocksize=blocksize,
            callback=_callback,
        )

        try:
            stream.start()
        except Exception as exc:
            logger.error("Failed to start audio stream: %s", exc)
            self._recording = False
            self.status_changed.emit("Voice: recording failed")
            return

        # ── Wait for recording to end ──────────────────────────────────────
        try:
            while self._recording and not stop_called:
                await asyncio.sleep(0.05)
        finally:
            stream.stop()
            stream.close()

        self._recording = False
        self.recording_stopped.emit()
        self.status_changed.emit("Transcribing…")

        # ── Concatenate captured audio ────────────────────────────────────
        if not buffers:
            self.transcription_failed.emit("No audio captured")
            self.status_changed.emit("Voice: no audio")
            return

        audio = np.concatenate(buffers, axis=0)
        if audio.ndim > 1:
            audio = audio.squeeze()
        audio = audio.astype(np.float32)

        # ── Transcribe ─────────────────────────────────────────────────────
        await self._transcribe_audio(audio)

    def _on_ptt_release(self) -> None:
        """Handler for PTT release.

        Stops the active recording.  The async :meth:`_start_ptt` loop will
        pick up the flag change, stop the stream, and transcribe.
        """
        self._recording = False

    async def _transcribe_audio(self, audio: np.ndarray) -> None:
        """Run speech-to-text on captured audio and emit the result.

        Args:
            audio: 1-D float32 array of audio samples ([-1, 1] range).
        """
        # ── Lazy-init recognizer if needed ────────────────────────────────
        if self._recognizer is None and self._model_manager is not None:
            try:
                from agent_uia.audio.recognizer import SpeechRecognizer

                self._recognizer = SpeechRecognizer(
                    model_manager=_ModelProvider(self._model_manager),
                    model_size=self._config.asr_model,
                )
            except ImportError as exc:
                self.transcription_failed.emit(
                    f"Speech recognition unavailable: {exc}"
                )
                self.status_changed.emit("Voice: recognizer unavailable")
                return

        if self._recognizer is None:
            self.transcription_failed.emit(
                "Speech recognizer not available"
            )
            self.status_changed.emit("Voice: recognizer unavailable")
            return

        # ── Run transcription in thread pool (CPU-bound) ──────────────────
        try:
            result = await asyncio.to_thread(
                self._recognizer.transcribe,
                audio,
                16000,
                "zh",
            )
        except Exception as exc:
            logger.exception("Transcription failed")
            self.transcription_failed.emit(f"Transcription failed: {exc}")
            self.status_changed.emit("Voice: transcription error")
            return

        # ── Emit result ────────────────────────────────────────────────────
        if result.text:
            self._on_transcription_ready(result.text)
        else:
            self.transcription_failed.emit("No speech detected")
            self.status_changed.emit("Voice: no speech detected")

    def _on_transcription_ready(self, text: str) -> None:
        """Handle a successful transcription.

        If the floating window input is empty the transcribed text fills it
        and is auto-submitted.  If the input already has content the text is
        appended.
        """
        self.transcription_ready.emit(text)
        self.status_changed.emit("Voice: transcribed")

        if self._floating is None:
            return

        current = self._floating.input_text()
        if not current.strip():
            # Empty input → fill and auto-submit.
            self._floating.set_input(text)
            # Schedule submission on the event loop.
            asyncio.create_task(self.run_task(text))
        else:
            # Non-empty → append with a space.
            self._floating.set_input(f"{current} {text}")

    # ══════════════════════════════════════════════════════════════════════
    #  Voice pipeline — TTS
    # ══════════════════════════════════════════════════════════════════════

    def toggle_tts(self) -> None:
        """Toggle the ``enable_tts`` flag.

        Because ``AppConfig`` is frozen, this creates a new config instance
        via ``model_copy()``.
        """
        self._config = self._config.model_copy(
            update={"enable_tts": not self._config.enable_tts}
        )
        status = "enabled" if self._config.enable_tts else "disabled"
        logger.info("TTS %s", status)
        self.status_changed.emit(f"TTS {status}")
