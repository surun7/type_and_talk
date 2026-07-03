# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""TOML-backed config store for TNT.

Schema (on disk)::

    [api]
    deepseek_api_key = "..."
    deepseek_base_url = "https://api.deepseek.com"
    deepseek_model = "deepseek-flash"

    [hotkey]
    toggle_floating_window = "ctrl+shift+space"
    ptt = "ctrl+shift+v"
    main_window = "ctrl+shift+m"

    [asr]
    model = "base"
    download_mirror = "https://huggingface.co"
    voice_opted_out = false

    [tts]
    enabled = false
    voice = "zh-CN-XiaoxiaoNeural"
    rate = "+0%"

    [recording]
    silence_timeout_s = 1.5
    max_duration_s = 60.0

    [planner]
    max_steps = 20
    max_cost_usd = 0.10
    auto_hide_floating_window = "on_success"

    [ui]
    theme = "dark"

Migration: older configs missing fields fall back to AppConfig() defaults.
"""

from __future__ import annotations

import os
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from agent_uia.paths import get_app_data_dir

__all__ = [
    "ConfigCorruptError",
    "ConfigStore",
]

# ── exceptions ─────────────────────────────────────────────────────────────────


class ConfigCorruptError(Exception):
    """Raised when the config file cannot be parsed.

    Attributes:
        original_error: The underlying parse exception.
        backup_path:    Path the corrupt file was moved to.
    """

    def __init__(self, original_error: Exception, backup_path: Path) -> None:
        self.original_error = original_error
        self.backup_path = backup_path
        super().__init__(
            f"Config file is corrupt — backed up to {backup_path}. "
            f"Original error: {original_error}"
        )


# ── TOML ↔ AppConfig field mapping ─────────────────────────────────────────────

_TOML_TO_APP_CONFIG: dict[tuple[str, ...], str] = {
    ("hotkey", "toggle_floating_window"): "hotkey",
    ("hotkey", "ptt"): "ptt_hotkey",
    ("asr", "model"): "asr_model",
    ("asr", "download_mirror"): "download_mirror",
    ("asr", "voice_opted_out"): "voice_opted_out",
    ("tts", "enabled"): "enable_tts",
    ("tts", "voice"): "tts_voice",
    ("tts", "rate"): "tts_rate",
    ("recording", "silence_timeout_s"): "ptt_release_silence_timeout_s",
    ("recording", "max_duration_s"): "ptt_max_duration_s",
    ("planner", "auto_hide_floating_window"): "floating_window_hide_policy",
    ("ui", "theme"): "theme",
}

_APP_CONFIG_TO_TOML: dict[str, tuple[str, ...]] = {
    fld: key for key, fld in _TOML_TO_APP_CONFIG.items()
}

# Fields stored in TOML but not part of AppConfig (extra metadata).
_EXTRA_TOML_KEYS: set[tuple[str, ...]] = {
    ("api", "deepseek_api_key"),
    ("api", "deepseek_base_url"),
    ("api", "deepseek_model"),
    ("hotkey", "main_window"),
    ("planner", "max_steps"),
    ("planner", "max_cost_usd"),
}


def _get_nested(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Traverse nested dicts following *path*."""
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


def _set_nested(
    data: dict[str, Any], path: tuple[str, ...], value: Any
) -> None:
    """Set a value in a nested dict, creating intermediate dicts as needed."""
    current = data
    for key in path[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current[path[-1]] = value


def _build_toml_dict(
    config: AppConfig, extra: dict[str, Any]
) -> dict[str, Any]:
    """Serialise an ``AppConfig`` + extra fields to a TOML-compatible dict.

    Args:
        config: The application configuration to serialise.
        extra:  Extra fields keyed by dotted path (e.g. ``"api.deepseek_api_key"``).

    Returns:
        A nested dict ready for ``tomli_w.dump()``.
    """
    data: dict[str, Any] = {}
    from agent_uia.ui.app_controller import AppConfig

    default_config = AppConfig()

    # Map all AppConfig fields to their TOML paths.
    for field_name, toml_key in _APP_CONFIG_TO_TOML.items():
        value = getattr(config, field_name, getattr(default_config, field_name, None))
        if value is not None:
            _set_nested(data, toml_key, value)

    # Extra fields (api, planner limits, main_window hotkey).
    for dotted_key, raw_value in extra.items():
        parts = tuple(dotted_key.split("."))
        _set_nested(data, parts, raw_value)

    return data


def _apply_toml_to_appconfig(
    data: dict[str, Any],
    base: AppConfig | None = None,
) -> AppConfig:
    """Merge TOML data into an AppConfig (defaults for missing fields).

    Args:
        data: The parsed TOML dict.
        base: Optional base config to merge into. If ``None`` a fresh
              ``AppConfig()`` with all-defaults is used as the base.

    Returns:
        A new ``AppConfig`` instance.
    """
    base = base
    from agent_uia.ui.app_controller import AppConfig

    base = base or AppConfig()
    update: dict[str, Any] = {}

    for toml_key, field_name in _TOML_TO_APP_CONFIG.items():
        value = _get_nested(data, toml_key)
        if value is not None:
            update[field_name] = value

    return base.model_copy(update=update)


# ── ConfigStore ────────────────────────────────────────────────────────────────


class ConfigStore:
    """TOML-backed persistence for ``AppConfig`` and extra metadata.

    Reads from ``get_app_data_dir() / "config.toml"`` by default.

    Usage::

        store = ConfigStore()
        config = store.load()
        config = config.model_copy(update={"theme": "light"})
        store.save(config)
    """

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialise the store.

        Args:
            config_path: Path to the TOML file. Defaults to
                ``<app_data_dir>/config.toml``, creating the parent
                directory if absent.
        """
        self._path = config_path or (get_app_data_dir() / "config.toml")
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Extra fields that live in TOML but aren't part of AppConfig.
        self._extra: dict[str, Any] = {}

    # ── public accessors for extra fields ──────────────────────────────────────

    @property
    def path(self) -> Path:
        """The config file path."""
        return self._path

    @property
    def api_key(self) -> SecretStr | None:
        """The DeepSeek API key (wrapped in ``SecretStr``)."""
        raw = self._extra.get("api.deepseek_api_key")
        return SecretStr(raw) if raw else None

    @property
    def base_url(self) -> str:
        """The DeepSeek base URL."""
        return self._extra.get("api.deepseek_base_url", "https://api.deepseek.com")

    @property
    def model(self) -> str:
        """The DeepSeek model name."""
        return self._extra.get("api.deepseek_model", "deepseek-chat")

    @property
    def main_window_hotkey(self) -> str:
        """The main-window toggle hotkey."""
        return self._extra.get("hotkey.main_window", "ctrl+shift+m")

    @property
    def planner_max_steps(self) -> int:
        """Maximum planner steps per task."""
        return int(self._extra.get("planner.max_steps", 20))

    @property
    def planner_max_cost_usd(self) -> float:
        """Maximum cost per task in USD."""
        return float(self._extra.get("planner.max_cost_usd", 0.10))

    # ── load / save / exists / backup ─────────────────────────────────────────

    def load(self) -> AppConfig:
        """Read the TOML file and return an ``AppConfig``.

        Missing fields fall back to ``AppConfig()`` defaults.

        Raises:
            ConfigCorruptError: If the TOML cannot be parsed. The corrupt
                file is backed up automatically.
        """
        if not self._path.exists():
            from agent_uia.ui.app_controller import AppConfig
            return AppConfig()

        try:
            raw = self._path.read_bytes()
            data = tomllib.loads(raw.decode("utf-8"))
        except (tomllib.TOMLDecodeError, ValueError, OSError) as exc:
            backup = self.backup_corrupt()
            raise ConfigCorruptError(
                original_error=exc, backup_path=backup
            ) from exc

        # Extract extra fields not in AppConfig.
        self._extra = {}
        for key_path in _EXTRA_TOML_KEYS:
            value = _get_nested(data, key_path)
            if value is not None:
                dotted = ".".join(key_path)
                self._extra[dotted] = value

        # Wrap API key in SecretStr.
        api_raw = self._extra.get("api.deepseek_api_key")
        if api_raw and not isinstance(api_raw, SecretStr):
            self._extra["api.deepseek_api_key"] = SecretStr(str(api_raw))

        return _apply_toml_to_appconfig(data)

    def save(self, config: AppConfig) -> None:
        """Write the config atomically to the TOML file.

        Args:
            config: The configuration to persist.

        Raises:
            ImportError: If ``tomli_w`` is not installed.
        """
        try:
            import tomli_w
        except ImportError as exc:
            raise ImportError(
                "tomli_w is required for saving config. "
                "Install it with: pip install tomli-w"
            ) from exc

        # Prepare extra fields for serialisation (unwrap SecretStr).
        extra_plain: dict[str, Any] = {}
        for dotted_key, value in self._extra.items():
            if isinstance(value, SecretStr):
                extra_plain[dotted_key] = value.get_secret_value()
            else:
                extra_plain[dotted_key] = value

        data = _build_toml_dict(config, extra_plain)

        # Write to .tmp then atomically replace.
        tmp_path = self._path.with_suffix(".toml.tmp")
        tmp_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(tmp_path, "wb") as fh:
                tomli_w.dump(data, fh)
            os.replace(tmp_path, self._path)
        except OSError:
            tmp_path.unlink(missing_ok=True)
            raise

    def exists(self) -> bool:
        """Return whether a config file exists on disk."""
        return self._path.is_file()

    def backup_corrupt(self) -> Path:
        """Move the corrupt config file to a timestamped backup path.

        Returns:
            The backup path.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = self._path.with_name(
            f"{self._path.stem}.corrupt-{timestamp}.bak"
        )
        if self._path.exists():
            os.replace(self._path, backup)
        return backup
