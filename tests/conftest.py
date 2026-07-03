# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Shared test configuration — forces offscreen Qt rendering for all UI tests."""

from __future__ import annotations

import os

# Force offscreen rendering before any Qt import.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
