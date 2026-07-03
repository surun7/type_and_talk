# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Models are downloaded once and cached locally. Subsequent runs are instant.
The mirror URL is configurable for users behind firewalls or in regions where
huggingface.co is slow.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from agent_uia.paths import get_model_path, get_models_dir
from agent_uia.performance.monitor import default_monitor, MetricType, MetricPoint

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import huggingface_hub with a user-friendly error message
# ---------------------------------------------------------------------------
try:
    from huggingface_hub import snapshot_download
except ImportError:
    _hub_error_message = (
        "The 'huggingface_hub' package is required to download model weights.\n"
        "Install it with: pip install huggingface_hub"
    )

    def _raise_hub_import_error(*args, **kwargs):  # type: ignore[misc]
        raise ImportError(_hub_error_message)

    snapshot_download = _raise_hub_import_error  # type: ignore[assignment]
    _hub_available = False
else:
    _hub_available = True

# ---------------------------------------------------------------------------
# Callback type
# ---------------------------------------------------------------------------
ProgressCallback = Callable[[float, int, int], None]
"""Signature: ``on_progress(percent: float, bytes_downloaded: int, total_bytes: int)``"""


# ---------------------------------------------------------------------------
# ModelState enum
# ---------------------------------------------------------------------------
class ModelState(enum.Enum):
    """Installation state of a Whisper model on disk."""

    NOT_INSTALLED = "not_installed"
    DOWNLOADING = "downloading"
    READY = "ready"
    FAILED = "failed"
    VERIFYING = "verifying"


# ---------------------------------------------------------------------------
# ModelInfo dataclass
# ---------------------------------------------------------------------------
@dataclass
class ModelInfo:
    """Describes the current status of a model size on disk."""

    size: str
    """Model size label, e.g. ``"tiny"``, ``"base"``, …"""

    repo_id: str
    """Hugging Face repository identifier."""

    expected_size_bytes: int
    """Approximate total download size in bytes."""

    local_path: Path
    """Path where model files are (or will be) stored."""

    state: ModelState = ModelState.NOT_INSTALLED
    """Current installation state."""

    progress_percent: float = 0.0
    """Download progress percentage (0‑100)."""

    error_message: str = ""
    """Human-readable error message when *state* is ``FAILED``."""


# ---------------------------------------------------------------------------
# Known model sizes
# ---------------------------------------------------------------------------
KNOWN_MODEL_SIZES: dict[str, tuple[str, int]] = {
    "tiny": ("Systran/faster-whisper-tiny", 75_000_000),
    "base": ("Systran/faster-whisper-base", 140_000_000),
    "small": ("Systran/faster-whisper-small", 460_000_000),
    "medium": ("Systran/faster-whisper-medium", 1_500_000_000),
    "large-v3": ("Systran/faster-whisper-large-v3", 3_000_000_000),
}

# Files that must be present for a model to be considered *installed*.
_EXPECTED_FILES: tuple[str, ...] = (
    "model.bin",
    "model.ggml",
    "config.json",
    "tokenizer.json",
)

# Tokenizer vocabulary files – *any* one of these is sufficient.
_VOCAB_FILES: tuple[str, ...] = (
    "vocabulary.txt",
    "vocab.json",
    "merges.txt",
)


# ---------------------------------------------------------------------------
# Progress helper – wraps huggingface_hub's ``on_progress`` signature
# ---------------------------------------------------------------------------
def _make_on_progress(
    user_callback: Optional[ProgressCallback],
    total_bytes: int,
) -> Callable:
    """Return a callable that forwards to *user_callback* in the expected shape.

    ``huggingface_hub`` passes ``(bytes_downloaded, total_bytes, new_download)``.
    We translate that to ``(percent, bytes_downloaded, total_bytes)``.
    """
    if user_callback is None:
        return lambda *_: None

    def _progress(bytes_downloaded: int, _total: int, _new: bool) -> None:
        percent = (bytes_downloaded / total_bytes) * 100.0 if total_bytes else 0.0
        user_callback(percent, bytes_downloaded, total_bytes)

    return _progress


# ---------------------------------------------------------------------------
# ModelManager
# ---------------------------------------------------------------------------
class ModelManager:
    """Manages download, verification, and cache of Whisper model weights.

    Parameters
    ----------
    models_dir:
        Directory under which per-model subdirectories are stored.
    mirror:
        Hugging Face mirror URL (defaults to ``https://huggingface.co``).
        Set ``os.environ["HF_ENDPOINT"]`` to this value on construction.
    """

    def __init__(
        self,
        models_dir: Path,
        mirror: str = "https://huggingface.co",
    ) -> None:
        self._models_dir = models_dir
        self._mirror = mirror

        # Ensure mirror is set for the huggingface_hub client.
        os.environ["HF_ENDPOINT"] = mirror

        # Concurrency control for coalescing downloads.
        self._lock = threading.Lock()
        self._active_downloads: dict[str, asyncio.Event] = {}
        self._download_results: dict[str, Path] = {}

        logger.info("ModelManager initialized (mirror=%s, models_dir=%s)", mirror, models_dir)

    # ------------------------------------------------------------------
    # list_available
    # ------------------------------------------------------------------
    async def list_available(self) -> list[str]:
        """Return the list of known model-size names (e.g. ``"tiny"``)."""
        return sorted(KNOWN_MODEL_SIZES.keys())

    # ------------------------------------------------------------------
    # get_status
    # ------------------------------------------------------------------
    async def get_status(self, model_size: str) -> ModelInfo:
        """Check the local disk and return a ``ModelInfo`` for *model_size*.

        This method is lightweight (it only queries the filesystem) and will
        never start a download.
        """
        if model_size not in KNOWN_MODEL_SIZES:
            raise ValueError(
                f"Unknown model size {model_size!r}. "
                f"Available: {', '.join(sorted(KNOWN_MODEL_SIZES))}"
            )

        repo_id, expected_bytes = KNOWN_MODEL_SIZES[model_size]
        local_path = get_model_path(model_size)

        # Start by constructing the base info.
        info = ModelInfo(
            size=model_size,
            repo_id=repo_id,
            expected_size_bytes=expected_bytes,
            local_path=local_path,
        )

        # If we're currently downloading, reflect that.
        with self._lock:
            if model_size in self._active_downloads:
                info.state = ModelState.DOWNLOADING
                # We could optionally track partial progress here.
                return info

        # Check whether the expected files exist on disk.
        if self._check_files_exist(local_path):
            info.state = ModelState.READY
        else:
            info.state = ModelState.NOT_INSTALLED

        return info

    # ------------------------------------------------------------------
    # download
    # ------------------------------------------------------------------
    async def download(
        self,
        model_size: str,
        *,
        on_progress: Optional[ProgressCallback] = None,
    ) -> Path:
        """Download (if needed) the model *model_size* to local cache.

        If another coroutine is already downloading the same *model_size* this
        call will wait for that download to finish and return the same path
        (download coalescing).

        Parameters
        ----------
        model_size:
            One of the keys in :data:`KNOWN_MODEL_SIZES`.
        on_progress:
            Optional callback invoked with ``(percent, bytes_downloaded,
            total_bytes)`` during download.

        Returns
        -------
        Path
            Local directory containing the model files.

        Raises
        ------
        ValueError
            For unknown model sizes.
        RuntimeError
            If the underlying ``huggingface_hub`` import is missing.
        """
        if model_size not in KNOWN_MODEL_SIZES:
            raise ValueError(
                f"Unknown model size {model_size!r}. "
                f"Available: {', '.join(sorted(KNOWN_MODEL_SIZES))}"
            )

        if not _hub_available:
            raise RuntimeError(_hub_error_message)

        repo_id, expected_bytes = KNOWN_MODEL_SIZES[model_size]
        local_path = get_model_path(model_size)

        # Fast-path: already downloaded.
        if self._check_files_exist(local_path):
            return local_path

        # --- Coalesce concurrent downloads ---
        event: Optional[asyncio.Event] = None

        with self._lock:
            if model_size in self._active_downloads:
                # Another task is already downloading – wait for it.
                event = self._active_downloads[model_size]

        if event is not None:
            logger.info("Waiting for concurrent download of %s …", model_size)
            await event.wait()
            # After the event is set the result is cached.
            with self._lock:
                result = self._download_results.get(model_size)
            if result is not None:
                return result
            # Fall-through to retry if the concurrent download failed.

        # --- Acquire the download slot ---
        with self._lock:
            if model_size in self._active_downloads:
                # Race: someone else claimed it between our two checks.
                event = self._active_downloads[model_size]

        if event is not None:
            await event.wait()
            with self._lock:
                result = self._download_results.get(model_size)
            if result is not None:
                return result

        # We are the designated downloader.
        my_event = asyncio.Event()
        with self._lock:
            self._active_downloads[model_size] = my_event
            # Clear any previous cached result so we get a fresh one.
            self._download_results.pop(model_size, None)

        try:
            _monitor = default_monitor()
            async with _monitor.time_async("asr_download", model_size=model_size):
                result = await self._do_download(
                    repo_id=repo_id,
                    local_path=local_path,
                    expected_bytes=expected_bytes,
                    on_progress=on_progress,
                )
            _monitor.record(MetricPoint(
                name="asr_download_status",
                type=MetricType.GAUGE,
                value=1,
                tags={"model_size": model_size},
            ))
            # Cache the successful result.
            with self._lock:
                self._download_results[model_size] = result
            return result
        finally:
            my_event.set()
            with self._lock:
                self._active_downloads.pop(model_size, None)

    # ------------------------------------------------------------------
    # _do_download (actual I/O in thread pool with retries)
    # ------------------------------------------------------------------
    async def _do_download(
        self,
        repo_id: str,
        local_path: Path,
        expected_bytes: int,
        on_progress: Optional[ProgressCallback] = None,
    ) -> Path:
        """Perform the snapshot download with retry logic."""

        logger.info("Downloading %s to %s …", repo_id, local_path)
        local_path.mkdir(parents=True, exist_ok=True)

        progress = _make_on_progress(on_progress, expected_bytes)

        max_retries = 3
        last_exception: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                await asyncio.to_thread(
                    snapshot_download,
                    repo_id=repo_id,
                    local_dir=str(local_path),
                    local_dir_use_symlinks=False,
                    max_workers=4,
                    on_progress=progress,
                )
                logger.info("Download of %s completed successfully.", repo_id)
                return local_path

            except Exception as exc:
                last_exception = exc
                logger.warning(
                    "Download attempt %d/%d failed for %s: %s",
                    attempt,
                    max_retries,
                    repo_id,
                    exc,
                )
                if attempt < max_retries:
                    # Brief back-off before retry.
                    await asyncio.sleep(1.0 * attempt)

        raise RuntimeError(
            f"Failed to download {repo_id} after {max_retries} attempts. "
            f"Last error: {last_exception}"
        ) from last_exception

    # ------------------------------------------------------------------
    # delete
    # ------------------------------------------------------------------
    async def delete(self, model_size: str) -> None:
        """Remove the local directory for *model_size* (if it exists)."""
        if model_size not in KNOWN_MODEL_SIZES:
            raise ValueError(
                f"Unknown model size {model_size!r}. "
                f"Available: {', '.join(sorted(KNOWN_MODEL_SIZES))}"
            )

        local_path = get_model_path(model_size)
        if not local_path.exists():
            logger.info("Model %s not found on disk; nothing to delete.", model_size)
            return

        await asyncio.to_thread(self._rmtree, local_path)
        logger.info("Deleted model %s from %s", model_size, local_path)

    @staticmethod
    def _rmtree(path: Path) -> None:
        """Recursively remove *path*."""
        import shutil

        shutil.rmtree(str(path), ignore_errors=False)

    # ------------------------------------------------------------------
    # verify
    # ------------------------------------------------------------------
    async def verify(self, model_size: str) -> bool:
        """Check that all expected files exist for *model_size*.

        Returns ``True`` if the model is fully installed, ``False`` otherwise.
        """
        if model_size not in KNOWN_MODEL_SIZES:
            raise ValueError(
                f"Unknown model size {model_size!r}. "
                f"Available: {', '.join(sorted(KNOWN_MODEL_SIZES))}"
            )

        local_path = get_model_path(model_size)
        return self._check_files_exist(local_path)

    # ------------------------------------------------------------------
    # _check_files_exist  (internal helper)
    # ------------------------------------------------------------------
    @staticmethod
    def _check_files_exist(local_path: Path) -> bool:
        """Return ``True`` if the expected model files are present on disk.

        Checks for the presence of at least one model binary (``model.bin``
        or ``model.ggml``), plus ``config.json``, ``tokenizer.json``, and
        at least one tokenizer vocabulary file.
        """
        if not local_path.is_dir():
            return False

        # At least one model-weight file.
        has_model_bin = False
        for fname in ("model.bin", "model.ggml"):
            if (local_path / fname).is_file():
                has_model_bin = True
                break
        if not has_model_bin:
            return False

        # Required metadata files.
        for fname in ("config.json", "tokenizer.json"):
            if not (local_path / fname).is_file():
                return False

        # At least one vocabulary file.
        has_vocab = False
        for fname in _VOCAB_FILES:
            if (local_path / fname).is_file():
                has_vocab = True
                break

        return has_vocab
