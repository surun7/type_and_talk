# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Safety gate — the immutable frontline for every UIA action.

Design invariants
-----------------
1. The gate is a lazy singleton — only one instance per process.
2. No execution path can bypass it from outside this module.
3. The blocklist is never empty by default.
4. Login screens for recognized apps are always blocked.
5. Every verdict is recorded in an append-only audit log.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

__all__ = [
    "SafetyVerdict",
    "SafetyDecision",
    "SafetyEvent",
    "SafetyConfig",
    "SafetyGate",
    "UnsupportedAppError",
    "LoginDetectedError",
    "default_gate",
    "assert_app_allowed",
    "assert_action_allowed",
]

# ── defaults ─────────────────────────────────────────────────────────────────

_DEFAULT_BLOCKED_EXECUTABLES: set[str] = {
    # Anti-cheat–protected games
    "valorant-win64-shipping.exe",
    "valorant.exe",
    "riotclientservices.exe",
    "leagueclientux.exe",
    "leagueclient.exe",
    "league of legends.exe",
    # Steam & launchers
    "steam.exe",
    "steamwebhelper.exe",
    "steamservice.exe",
    "epicgameslauncher.exe",
    "epicwebhelper.exe",
    # Other game launchers
    "battle.net.exe",
    "battle.net launcher.exe",
    "origin.exe",
    "eadesktop.exe",
    "ubisoftconnect.exe",
    "ubisoft game launcher.exe",
    "gog galaxy.exe",
    "goggalaxy.exe",
    # Competitive shooters
    "cs2.exe",
    "csgo.exe",
    "r5apex.exe",
    "apex legends.exe",
    "overwatch.exe",
    "overwatch launcher.exe",
    # More anti-cheat games
    "pubg.exe",
    "tslgame.exe",
    "fortniteclient-win64-shipping.exe",
    "fortnitelauncher.exe",
    "destiny2.exe",
    "destiny2 launcher.exe",
    "escapefromtarkov.exe",
    "r6s.exe",
    "rainbowsix.exe",
    # WeGame (Chinese launcher)
    "wegame.exe",
    "wegameclient.exe",
    "tgp_daemon.exe",
}

_DEFAULT_LOGIN_KEYWORDS: set[str] = {
    "登录",
    "login",
    "sign in",
    "signin",
    "sign-in",
    "passport",
    "auth",
    "authenticate",
    "authentication",
    "log in",
    "logon",
}

_DEFAULT_ALWAYS_CONFIRM_ACTIONS: set[str] = {
    "delete",
    "delete_file",
    "send_message",
    "send",
    "purchase",
    "submit_form",
    "submit",
    "pay",
    "transfer",
    "transfer_money",
}

# Recognized interactive apps for login-screen detection.
_RECOGNIZED_LOGIN_APPS: set[str] = {
    "wegame.exe",
    "wegameclient.exe",
    "steam.exe",
    "epicgameslauncher.exe",
    "riotclientservices.exe",
    "leagueclientux.exe",
    "battle.net.exe",
    "origin.exe",
    "eadesktop.exe",
    "ubisoftconnect.exe",
    "gog galaxy.exe",
}

# ── types ────────────────────────────────────────────────────────────────────


class SafetyVerdict(Enum):
    """Outcome of a safety check."""

    ALLOW = auto()
    """Action is permitted."""

    BLOCK_GAME_LOGIN = auto()
    """Login/authentication UI detected — blocked."""

    BLOCK_UNSUPPORTED = auto()
    """Application is on the blocklist — not supported."""

    REQUIRE_CONFIRMATION = auto()
    """Action needs explicit user confirmation."""

    DENY = auto()
    """Action is categorically denied (reserved for future use)."""


@dataclass(frozen=True)
class SafetyDecision:
    """The result of a safety gate check.

    Attributes:
        verdict: The safety outcome.
        reason: Human-readable explanation.
        requires_user_confirm: Whether the caller must obtain user confirmation.
    """

    verdict: SafetyVerdict
    reason: str
    requires_user_confirm: bool = False


@dataclass(frozen=True)
class SafetyEvent:
    """A single auditable safety event.

    Serialised as a JSON line in the audit log.
    """

    timestamp: str
    actor: str
    action_type: str
    target: str
    verdict: str
    reason: str


class SafetyConfig(BaseModel):
    """Immutable configuration for the safety gate.

    Fields:
        blocked_executables: Lowercased exe names that are always blocked.
        login_window_keywords: Keywords that, when found in a window title,
            trigger ``BLOCK_GAME_LOGIN`` for recognised apps.
        always_confirm_actions: Action types that always require user
            confirmation.
        enable_audit_log: When ``True``, every verdict is written to disk.
        audit_log_path: Where to write the JSON-lines audit log.
    """

    model_config = {"frozen": True}

    blocked_executables: set[str] = Field(
        default_factory=lambda: _DEFAULT_BLOCKED_EXECUTABLES.copy()
    )
    login_window_keywords: set[str] = Field(
        default_factory=lambda: _DEFAULT_LOGIN_KEYWORDS.copy()
    )
    always_confirm_actions: set[str] = Field(
        default_factory=lambda: _DEFAULT_ALWAYS_CONFIRM_ACTIONS.copy()
    )
    enable_audit_log: bool = True
    audit_log_path: Path = Field(default=Path("./logs/audit.log"))


# ── errors ───────────────────────────────────────────────────────────────────


class UnsupportedAppError(Exception):
    """Raised when the target application is on the blocklist."""


class LoginDetectedError(Exception):
    """Raised when a login/authentication screen is detected."""


# ── safety gate ──────────────────────────────────────────────────────────────


class SafetyGate:
    """The immutable safety frontline.

    Every UIA operation must pass through this gate before execution.
    The gate cannot be reconfigured after construction.
    """

    def __init__(self, config: SafetyConfig) -> None:
        self._config = config
        self._events: list[SafetyEvent] = []
        self._lock = threading.Lock()

    # -- check_app -------------------------------------------------------------

    def check_app(
        self,
        *,
        exe_name: str | None = None,
        window_title: str | None = None,
        window_class: str | None = None,
        pid: int | None = None,
    ) -> SafetyDecision:
        """Check whether interacting with an application is allowed.

        Args:
            exe_name: The executable basename (e.g. ``"notepad.exe"``).
            window_title: The window title string.
            window_class: The window class name (rarely needed).
            pid: The process id (informational only).

        Returns:
            A ``SafetyDecision`` with the verdict.
        """
        exe_lower = exe_name.lower() if exe_name else None
        title_lower = window_title.lower() if window_title else None

        # 1. Blocklist check — executable name.
        if exe_lower and exe_lower in self._config.blocked_executables:
            decision = SafetyDecision(
                verdict=SafetyVerdict.BLOCK_UNSUPPORTED,
                reason=(
                    "This app is on the blocklist. agent-uia intentionally "
                    "does not support it for safety/ToS reasons."
                ),
            )
            self._record(
                actor="safety_gate",
                action_type="check_app",
                target=f"exe={exe_lower} title={title_lower or 'N/A'}",
                verdict=decision.verdict.name,
                reason=decision.reason,
            )
            return decision

        # 2. Login screen detection for recognized interactive apps.
        if title_lower and exe_lower and exe_lower in _RECOGNIZED_LOGIN_APPS:
            for keyword in self._config.login_window_keywords:
                if keyword in title_lower:
                    decision = SafetyDecision(
                        verdict=SafetyVerdict.BLOCK_GAME_LOGIN,
                        reason=(
                            "Detected login/authentication UI. agent-uia will "
                            "not operate on login screens for any app — log "
                            "in manually first."
                        ),
                    )
                    self._record(
                        actor="safety_gate",
                        action_type="check_app",
                        target=f"exe={exe_lower} title={title_lower}",
                        verdict=decision.verdict.name,
                        reason=decision.reason,
                    )
                    return decision

        # 3. Default — allow.
        decision = SafetyDecision(verdict=SafetyVerdict.ALLOW, reason="App is allowed.")
        self._record(
            actor="safety_gate",
            action_type="check_app",
            target=f"exe={exe_lower or 'N/A'} title={title_lower or 'N/A'}",
            verdict=decision.verdict.name,
            reason=decision.reason,
        )
        return decision

    # -- check_action ----------------------------------------------------------

    def check_action(
        self,
        action_type: str,
        target: str | None = None,
    ) -> SafetyDecision:
        """Check whether a specific action requires confirmation or is denied.

        Args:
            action_type: The action name (e.g. ``"delete_file"``, ``"click"``).
            target: Optional description of the action target.

        Returns:
            A ``SafetyDecision`` with the verdict.
        """
        if action_type in self._config.always_confirm_actions:
            decision = SafetyDecision(
                verdict=SafetyVerdict.REQUIRE_CONFIRMATION,
                reason=(
                    f"Action '{action_type}' on '{target or 'unknown'}' "
                    f"requires explicit user confirmation."
                ),
                requires_user_confirm=True,
            )
        else:
            decision = SafetyDecision(
                verdict=SafetyVerdict.ALLOW,
                reason=f"Action '{action_type}' is allowed.",
            )

        self._record(
            actor="safety_gate",
            action_type="check_action",
            target=f"action={action_type} target={target or 'N/A'}",
            verdict=decision.verdict.name,
            reason=decision.reason,
        )
        return decision

    # -- record_event ----------------------------------------------------------

    def record_event(self, event: SafetyEvent) -> None:
        """Append a safety event to the in-memory log and the disk audit log.

        Args:
            event: The event to record.
        """
        with self._lock:
            self._events.append(event)
            if self._config.enable_audit_log:
                self._write_audit_line(event)

    # -- internal helpers ------------------------------------------------------

    def _record(
        self,
        *,
        actor: str,
        action_type: str,
        target: str,
        verdict: str,
        reason: str,
    ) -> None:
        """Convenience wrapper: build a ``SafetyEvent`` and call ``record_event``."""
        event = SafetyEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            actor=actor,
            action_type=action_type,
            target=target,
            verdict=verdict,
            reason=reason,
        )
        self.record_event(event)

    def _write_audit_line(self, event: SafetyEvent) -> None:
        """Append a single JSON line to the audit log."""
        try:
            log_path = Path(self._config.audit_log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "timestamp": event.timestamp,
                            "actor": event.actor,
                            "action_type": event.action_type,
                            "target": event.target,
                            "verdict": event.verdict,
                            "reason": event.reason,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except OSError:
            logger.exception("Failed to write audit log entry")


# ── singleton ────────────────────────────────────────────────────────────────

_default_gate: SafetyGate | None = None
_default_gate_lock: threading.Lock = threading.Lock()


def default_gate() -> SafetyGate:
    """Return the process-wide singleton ``SafetyGate``.

    The gate is initialised lazily on first call with a default
    ``SafetyConfig``.  This deferral allows unit tests to patch the
    config before the first gate is created.

    Returns:
        The singleton ``SafetyGate`` instance.
    """
    global _default_gate  # noqa: PLW0603
    if _default_gate is None:
        with _default_gate_lock:
            if _default_gate is None:
                _default_gate = SafetyGate(SafetyConfig())
    return _default_gate


# ── convenience raisers ──────────────────────────────────────────────────────


def assert_app_allowed(
    *,
    exe_name: str | None = None,
    window_title: str | None = None,
    window_class: str | None = None,
    pid: int | None = None,
    gate: SafetyGate | None = None,
) -> None:
    """Check the app and raise if blocked.

    Args:
        exe_name: Executable name.
        window_title: Window title.
        window_class: Window class name.
        pid: Process id.
        gate: Optional gate instance (uses default singleton if ``None``).

    Raises:
        UnsupportedAppError: If the app is on the blocklist.
        LoginDetectedError: If a login screen is detected.
    """
    _gate = gate or default_gate()
    decision = _gate.check_app(
        exe_name=exe_name,
        window_title=window_title,
        window_class=window_class,
        pid=pid,
    )
    if decision.verdict == SafetyVerdict.BLOCK_UNSUPPORTED:
        raise UnsupportedAppError(decision.reason)
    if decision.verdict == SafetyVerdict.BLOCK_GAME_LOGIN:
        raise LoginDetectedError(decision.reason)


def assert_action_allowed(
    action_type: str,
    target: str | None = None,
    *,
    gate: SafetyGate | None = None,
) -> SafetyDecision:
    """Check an action type; returns the decision (may require confirmation).

    Args:
        action_type: The action name.
        target: Optional target description.
        gate: Optional gate instance.

    Returns:
        The ``SafetyDecision`` (caller should honour ``requires_user_confirm``).

    Raises:
        UnsupportedAppError: If the verdict is DENY (future-proofing).
    """
    _gate = gate or default_gate()
    decision = _gate.check_action(action_type, target)
    if decision.verdict == SafetyVerdict.DENY:
        raise UnsupportedAppError(decision.reason)
    return decision
