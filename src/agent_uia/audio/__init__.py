# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Voice input/output for Type and Talk.

Submodules:
    model_manager — Download / cache / verify Whisper model weights.
    recognizer   — Speech-to-text via faster-whisper (local, offline).
    recorder     — Audio capture via sounddevice (PortAudio).
    vad          — Voice-activity detection (silero-vad, RMS fallback).
    synthesizer  — Text-to-speech via Edge TTS (optional, opt-in).
"""
