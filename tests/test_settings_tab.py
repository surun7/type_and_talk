# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the settings tab — API key validation, test connection, and save."""

from __future__ import annotations

from unittest import mock

import pytest
from PySide6.QtWidgets import QApplication

from agent_uia.ui.app_controller import AppConfig


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def mock_llm_client():
    """Return a mocked LLMClient that succeeds on check_connection."""
    client = mock.MagicMock()
    client.check_connection = mock.AsyncMock(return_value=(True, "OK"))
    return client


@pytest.fixture
def mock_config_store():
    store = mock.MagicMock()
    store.save = mock.MagicMock()
    return store


@pytest.fixture
def settings_tab(qapp, mock_llm_client, mock_config_store, monkeypatch):
    """Build a SettingsTab with mocked dependencies."""
    from agent_uia.ui.settings_tab import SettingsTab

    monkeypatch.setattr(
        "agent_uia.ui.settings_tab.LLMClient", lambda cfg: mock_llm_client
    )

    st = SettingsTab(
        app_controller=mock.MagicMock(config=AppConfig()),
        config_store=mock_config_store,
    )
    yield st
    st.deleteLater()


class TestApiKeyValidation:
    """The API-key field must gate the Save button."""

    def test_invalid_key_disables_save(self, settings_tab):
        """Setting an empty API key must disable the Save button."""
        settings_tab.set_api_key("")
        assert not settings_tab.save_button.isEnabled(), (
            "Save button should be disabled for empty API key"
        )

    def test_valid_key_enables_save(self, settings_tab):
        """Setting a plausible non-empty API key must enable the Save button."""
        settings_tab.set_api_key("sk-" + "a" * 48)
        assert settings_tab.save_button.isEnabled(), (
            "Save button should be enabled for a valid-looking API key"
        )


class TestConnection:
    """The "Test connection" button must invoke LLMClient and show the result."""

    def test_test_connection_success(self, settings_tab, mock_llm_client):
        """When check_connection returns (True, msg), the result label must
        show a success message."""
        mock_llm_client.check_connection = mock.AsyncMock(
            return_value=(True, "Connected successfully")
        )

        settings_tab.test_connection_button.click()

        # The result label should indicate success.
        label_text = settings_tab.connection_result_label.text().lower()
        assert "ok" in label_text or "success" in label_text or "connected" in label_text

    def test_test_connection_failure(self, settings_tab, mock_llm_client):
        """When check_connection returns (False, msg), the result label must
        show the error."""
        mock_llm_client.check_connection = mock.AsyncMock(
            return_value=(False, "Invalid API key")
        )

        settings_tab.test_connection_button.click()

        label_text = settings_tab.connection_result_label.text().lower()
        assert "invalid" in label_text or "error" in label_text or "fail" in label_text


class TestSave:
    """Pressing Save must persist the config."""

    def test_save_calls_config_store_save(self, settings_tab, mock_config_store):
        """Clicking Save must call config_store.save with the current config."""
        settings_tab.set_api_key("sk-" + "b" * 48)
        settings_tab.save_button.click()

        mock_config_store.save.assert_called_once()
        # The argument should be an AppConfig (or compatible) instance.
        saved_config = mock_config_store.save.call_args[0][0]
        assert saved_config is not None
