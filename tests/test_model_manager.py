# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for ModelManager — huggingface_hub.snapshot_download is mocked throughout."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest import mock

import pytest

from agent_uia.audio.model_manager import (
    KNOWN_MODEL_SIZES,
    ModelInfo,
    ModelManager,
    ModelState,
    _make_on_progress,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    """Return a temporary directory to serve as the model cache root."""
    return tmp_path / "models"


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch, models_dir: Path) -> ModelManager:
    """Return a ModelManager whose get_model_path is redirected to *models_dir*."""

    def fake_get_model_path(model_size: str) -> Path:
        return models_dir / f"faster-whisper-{model_size}"

    monkeypatch.setattr(
        "agent_uia.audio.model_manager.get_model_path", fake_get_model_path
    )
    monkeypatch.setattr(
        "agent_uia.audio.model_manager.get_models_dir", lambda: models_dir
    )

    return ModelManager(models_dir=models_dir)


@pytest.fixture(autouse=True)
def _clear_hf_endpoint() -> None:
    """Ensure HF_ENDPOINT is removed before each test so mirror tests are clean."""
    os.environ.pop("HF_ENDPOINT", None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_model_dir(model_size: str, models_dir: Path) -> Path:
    """Create a fake model directory with the expected files so the model is READY."""
    local_path = models_dir / f"faster-whisper-{model_size}"
    local_path.mkdir(parents=True, exist_ok=True)
    # model.bin (one of the two model-weight files)
    (local_path / "model.bin").write_bytes(b"dummy")
    # Required metadata
    (local_path / "config.json").write_text("{}")
    (local_path / "tokenizer.json").write_text("{}")
    # Vocabulary file (at least one required)
    (local_path / "vocabulary.txt").write_text("dummy")
    return local_path


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    """Tests for ModelManager.get_status()."""

    @pytest.mark.asyncio
    async def test_status_not_installed(self, manager: ModelManager) -> None:
        """When no files exist at the local path, status is NOT_INSTALLED."""
        info = await manager.get_status("base")
        assert info.state == ModelState.NOT_INSTALLED
        assert info.size == "base"
        assert info.repo_id == "Systran/faster-whisper-base"

    @pytest.mark.asyncio
    async def test_status_ready(
        self, manager: ModelManager, models_dir: Path
    ) -> None:
        """When all expected files exist, status is READY."""
        _make_model_dir("base", models_dir)
        info = await manager.get_status("base")
        assert info.state == ModelState.READY

    @pytest.mark.asyncio
    async def test_status_ready_with_ggml(self, manager: ModelManager, models_dir: Path) -> None:
        """The model-weight file can be model.ggml instead of model.bin."""
        local_path = models_dir / "faster-whisper-base"
        local_path.mkdir(parents=True, exist_ok=True)
        (local_path / "model.ggml").write_bytes(b"dummy")
        (local_path / "config.json").write_text("{}")
        (local_path / "tokenizer.json").write_text("{}")
        (local_path / "vocab.json").write_text("{}")

        info = await manager.get_status("base")
        assert info.state == ModelState.READY

    @pytest.mark.asyncio
    async def test_status_unknown_size(self, manager: ModelManager) -> None:
        """An unknown model size raises ValueError."""
        with pytest.raises(ValueError, match="Unknown model size"):
            await manager.get_status("nonexistent")

    @pytest.mark.asyncio
    async def test_status_downloading(
        self, manager: ModelManager, models_dir: Path
    ) -> None:
        """When a download is in progress, status reports DOWNLOADING."""
        # Manually insert into the active-downloads dict.
        with manager._lock:
            manager._active_downloads["base"] = asyncio.Event()
        try:
            info = await manager.get_status("base")
            assert info.state == ModelState.DOWNLOADING
        finally:
            with manager._lock:
                manager._active_downloads.pop("base", None)

    @pytest.mark.asyncio
    async def test_status_returns_correct_info(self, manager: ModelManager) -> None:
        """get_status returns ModelInfo with accurate metadata."""
        info = await manager.get_status("tiny")
        assert info.size == "tiny"
        assert info.repo_id == "Systran/faster-whisper-tiny"
        assert info.expected_size_bytes == 75_000_000
        assert info.local_path.name == "faster-whisper-tiny"


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------


class TestDownload:
    """Tests for ModelManager.download()."""

    @pytest.mark.asyncio
    async def test_download_invokes_hub(
        self, manager: ModelManager, models_dir: Path
    ) -> None:
        """download('base') calls snapshot_download with the right repo_id."""
        with mock.patch(
            "agent_uia.audio.model_manager.snapshot_download"
        ) as mock_sd:
            result = await manager.download("base")
            expected_path = models_dir / "faster-whisper-base"
            assert result == expected_path
            mock_sd.assert_called_once_with(
                repo_id="Systran/faster-whisper-base",
                local_dir=str(expected_path),
                local_dir_use_symlinks=False,
                max_workers=4,
                on_progress=mock.ANY,
            )

    @pytest.mark.asyncio
    async def test_download_skips_if_already_installed(
        self, manager: ModelManager, models_dir: Path
    ) -> None:
        """If the model directory is already complete, snapshot_download is not called."""
        _make_model_dir("base", models_dir)
        with mock.patch(
            "agent_uia.audio.model_manager.snapshot_download"
        ) as mock_sd:
            result = await manager.download("base")
            expected_path = models_dir / "faster-whisper-base"
            assert result == expected_path
            mock_sd.assert_not_called()

    @pytest.mark.asyncio
    async def test_download_retries_on_network_error(
        self, manager: ModelManager, models_dir: Path
    ) -> None:
        """A transient failure is retried; succeeds on the third attempt."""
        call_count = 0

        def _flaky_download(**kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Temporary network failure")
            return None

        with mock.patch(
            "agent_uia.audio.model_manager.snapshot_download", side_effect=_flaky_download
        ) as mock_sd:
            result = await manager.download("base")
            expected_path = models_dir / "faster-whisper-base"
            assert result == expected_path
            # Should have been called 3 times (fail, fail, succeed)
            assert mock_sd.call_count == 3

    @pytest.mark.asyncio
    async def test_download_failure_after_max_retries(
        self, manager: ModelManager, models_dir: Path
    ) -> None:
        """When all retries exhaust, the method raises RuntimeError."""
        with mock.patch(
            "agent_uia.audio.model_manager.snapshot_download",
            side_effect=ConnectionError("Always fails"),
        ):
            with pytest.raises(RuntimeError, match="Failed to download"):
                await manager.download("base")

    @pytest.mark.asyncio
    async def test_download_unknown_size(self, manager: ModelManager) -> None:
        """An unknown model size raises ValueError."""
        with pytest.raises(ValueError, match="Unknown model size"):
            await manager.download("nonexistent")

    @pytest.mark.asyncio
    async def test_progress_callback_fires(
        self, manager: ModelManager, models_dir: Path
    ) -> None:
        """Simulate progress events and verify the callback receives (percent, bytes, total)."""
        progress_events: list[tuple[float, int, int]] = []

        def on_progress(percent: float, downloaded: int, total: int) -> None:
            progress_events.append((percent, downloaded, total))

        # Mock snapshot_download to invoke the on_progress callback as
        # huggingface_hub would: (bytes_downloaded, total_bytes, new_download).
        def _invoke_progress(**kwargs: object) -> None:
            cb = kwargs.get("on_progress")
            if cb:
                cb(50, 100, False)  # halfway
                cb(100, 100, False)  # complete
            return None

        with mock.patch(
            "agent_uia.audio.model_manager.snapshot_download",
            side_effect=_invoke_progress,
        ):
            await manager.download("base", on_progress=on_progress)

        assert len(progress_events) == 2
        # First event: 50/100 = 50%
        assert progress_events[0] == (50.0, 50, 100)
        # Second event: 100/100 = 100%
        assert progress_events[1] == (100.0, 100, 100)

    @pytest.mark.asyncio
    async def test_progress_callback_none(self, manager: ModelManager) -> None:
        """Passing on_progress=None should not crash."""
        with mock.patch(
            "agent_uia.audio.model_manager.snapshot_download"
        ) as mock_sd:
            await manager.download("base", on_progress=None)
            mock_sd.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrent_downloads_coalesce(
        self, manager: ModelManager, models_dir: Path
    ) -> None:
        """Two simultaneous download('base') calls result in one underlying snapshot_download."""
        call_count = 0
        barrier_started = asyncio.Event()
        barrier_continue = asyncio.Event()

        async def _slow_download(**kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            barrier_started.set()
            await barrier_continue.wait()

        with mock.patch(
            "agent_uia.audio.model_manager.snapshot_download",
            side_effect=_slow_download,
        ):
            # Launch two concurrent downloads.
            async def do_download() -> Path:
                return await manager.download("base")

            task1 = asyncio.create_task(do_download())
            task2 = asyncio.create_task(do_download())

            # Wait until the first task has entered the download.
            await barrier_started.wait()
            # Give task2 a chance to reach the coalesce check.
            await asyncio.sleep(0.05)
            # Let both proceed.
            barrier_continue.set()

            results = await asyncio.gather(task1, task2, return_exceptions=True)

        # Both should succeed and return the same path.
        expected = models_dir / "faster-whisper-base"
        for r in results:
            assert not isinstance(r, Exception), f"Task failed: {r}"
            assert r == expected

        # snapshot_download should have been called exactly once.
        assert call_count == 1


# ---------------------------------------------------------------------------
# mirror / HF_ENDPOINT
# ---------------------------------------------------------------------------


class TestMirror:
    """Tests for mirror URL configuration."""

    def test_mirror_sets_hf_endpoint(self, models_dir: Path) -> None:
        """The constructor sets HF_ENDPOINT to the mirror URL."""
        assert "HF_ENDPOINT" not in os.environ or os.environ["HF_ENDPOINT"] == ""

        ModelManager(models_dir=models_dir, mirror="https://hf-mirror.com")

        assert os.environ["HF_ENDPOINT"] == "https://hf-mirror.com"

    def test_default_mirror_is_huggingface_co(self, models_dir: Path) -> None:
        """The default mirror value is https://huggingface.co."""
        ModelManager(models_dir=models_dir)

        assert os.environ["HF_ENDPOINT"] == "https://huggingface.co"

    def test_multiple_managers_update_endpoint(self, models_dir: Path) -> None:
        """Creating a second manager with a different mirror updates the env var."""
        ModelManager(models_dir=models_dir, mirror="https://hf-mirror.com")
        assert os.environ["HF_ENDPOINT"] == "https://hf-mirror.com"

        ModelManager(models_dir=models_dir, mirror="https://huggingface.co")
        assert os.environ["HF_ENDPOINT"] == "https://huggingface.co"


# ---------------------------------------------------------------------------
# list_available / delete / verify
# ---------------------------------------------------------------------------


class TestListAvailable:
    """Tests for ModelManager.list_available()."""

    @pytest.mark.asyncio
    async def test_list_available_returns_sorted_keys(self, manager: ModelManager) -> None:
        """list_available() returns sorted model size names."""
        sizes = await manager.list_available()
        assert sizes == sorted(KNOWN_MODEL_SIZES.keys())
        assert "base" in sizes
        assert "tiny" in sizes


class TestDelete:
    """Tests for ModelManager.delete()."""

    @pytest.mark.asyncio
    async def test_delete_removes_directory(
        self, manager: ModelManager, models_dir: Path
    ) -> None:
        """delete() removes the model directory from disk."""
        local_path = _make_model_dir("base", models_dir)
        assert local_path.exists()

        await manager.delete("base")
        assert not local_path.exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_is_noop(self, manager: ModelManager) -> None:
        """Deleting a model that is not on disk does not raise."""
        await manager.delete("base")  # should not raise

    @pytest.mark.asyncio
    async def test_delete_unknown_size_raises(self, manager: ModelManager) -> None:
        """An unknown model size raises ValueError."""
        with pytest.raises(ValueError, match="Unknown model size"):
            await manager.delete("nonexistent")


class TestVerify:
    """Tests for ModelManager.verify()."""

    @pytest.mark.asyncio
    async def test_verify_returns_true_when_ready(
        self, manager: ModelManager, models_dir: Path
    ) -> None:
        """verify() returns True when all expected files are present."""
        _make_model_dir("base", models_dir)
        assert await manager.verify("base") is True

    @pytest.mark.asyncio
    async def test_verify_returns_false_when_missing(
        self, manager: ModelManager,
    ) -> None:
        """verify() returns False when the model directory is absent."""
        assert await manager.verify("base") is False

    @pytest.mark.asyncio
    async def test_verify_unknown_size_raises(self, manager: ModelManager) -> None:
        """An unknown model size raises ValueError."""
        with pytest.raises(ValueError, match="Unknown model size"):
            await manager.verify("nonexistent")


# ---------------------------------------------------------------------------
# _make_on_progress helper
# ---------------------------------------------------------------------------


class TestMakeOnProgress:
    """Tests for the internal _make_on_progress helper."""

    def test_with_callback(self) -> None:
        """The wrapper translates (bytes, total, new) → (percent, bytes, total)."""
        events: list[tuple[float, int, int]] = []

        def cb(percent: float, downloaded: int, total: int) -> None:
            events.append((percent, downloaded, total))

        wrapped = _make_on_progress(cb, total_bytes=200)
        wrapped(50, 200, False)
        wrapped(150, 200, False)

        assert events == [
            (25.0, 50, 200),  # 50/200 = 25%
            (75.0, 150, 200),  # 150/200 = 75%
        ]

    def test_without_callback(self) -> None:
        """When the callback is None, the wrapper is a no-op."""
        wrapped = _make_on_progress(None, total_bytes=200)
        # Should not raise
        wrapped(50, 200, False)
        wrapped(100, 200, False)

    def test_zero_total_guard(self) -> None:
        """When total_bytes is 0, percent stays 0 to avoid division-by-zero."""
        events: list[tuple[float, int, int]] = []

        def cb(percent: float, downloaded: int, total: int) -> None:
            events.append((percent, downloaded, total))

        wrapped = _make_on_progress(cb, total_bytes=0)
        wrapped(100, 0, False)

        assert events == [(0.0, 100, 0)]
