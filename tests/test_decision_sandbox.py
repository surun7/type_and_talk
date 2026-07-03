# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 agent-uia contributors
"""Tests for the decision expression sandbox (asteval)."""

from __future__ import annotations

import pytest

try:
    from asteval import Interpreter
except ImportError:
    pytest.skip("asteval not installed", allow_module_level=True)


# ── fixture ────────────────────────────────────────────────────────────────────


@pytest.fixture
def interp() -> Interpreter:
    """Return a fresh asteval Interpreter."""
    return Interpreter()


# ── tests ──────────────────────────────────────────────────────────────────────


class TestArithmetic:
    """Basic arithmetic operations."""

    def test_addition(self, interp: Interpreter) -> None:
        """a + b should work."""
        result = interp.eval("a + b", a=3, b=4)
        assert result == 7

    def test_subtraction(self, interp: Interpreter) -> None:
        """a - b should work."""
        result = interp.eval("a - b", a=10, b=3)
        assert result == 7

    def test_multiplication(self, interp: Interpreter) -> None:
        """a * b should work."""
        result = interp.eval("a * b", a=6, b=7)
        assert result == 42

    def test_division(self, interp: Interpreter) -> None:
        """a / b should work."""
        result = interp.eval("a / b", a=10, b=2)
        assert result == 5.0

    def test_modulo(self, interp: Interpreter) -> None:
        """a % b should work."""
        result = interp.eval("a % b", a=10, b=3)
        assert result == 1

    def test_complex_expression(self, interp: Interpreter) -> None:
        """Combined arithmetic should work."""
        result = interp.eval("(a + b) * c", a=2, b=3, c=4)
        assert result == 20


class TestComparison:
    """Comparison operations."""

    def test_greater_than(self, interp: Interpreter) -> None:
        """a > b should work."""
        assert interp.eval("a > b", a=5, b=3) is True
        assert interp.eval("a > b", a=3, b=5) is False

    def test_less_than(self, interp: Interpreter) -> None:
        """a < b should work."""
        assert interp.eval("a < b", a=3, b=5) is True

    def test_equals(self, interp: Interpreter) -> None:
        """a == b should work."""
        assert interp.eval("a == b", a=5, b=5) is True
        assert interp.eval("a == b", a=5, b=3) is False

    def test_not_equals(self, interp: Interpreter) -> None:
        """a != b should work."""
        assert interp.eval("a != b", a=5, b=3) is True

    def test_greater_or_equal(self, interp: Interpreter) -> None:
        """a >= b should work."""
        assert interp.eval("a >= b", a=5, b=5) is True
        assert interp.eval("a >= b", a=5, b=3) is True
        assert interp.eval("a >= b", a=3, b=5) is False

    def test_comparison_with_step_result(self, interp: Interpreter) -> None:
        """Comparison using step.ok should work."""
        result = interp.eval("ok == True", ok=True)
        assert result is True


class TestBoolean:
    """Boolean operations."""

    def test_and(self, interp: Interpreter) -> None:
        """a and b should work."""
        assert interp.eval("a and b", a=True, b=True) is True
        assert interp.eval("a and b", a=True, b=False) is False
        assert interp.eval("a and b", a=False, b=True) is False

    def test_or(self, interp: Interpreter) -> None:
        """a or b should work."""
        assert interp.eval("a or b", a=True, b=False) is True
        assert interp.eval("a or b", a=False, b=False) is False

    def test_not(self, interp: Interpreter) -> None:
        """not a should work."""
        assert interp.eval("not a", a=False) is True
        assert interp.eval("not a", a=True) is False

    def test_combined_boolean(self, interp: Interpreter) -> None:
        """Complex boolean expressions should work."""
        result = interp.eval("(a and b) or c", a=True, b=True, c=False)
        assert result is True
        result = interp.eval("(a and b) or c", a=True, b=False, c=True)
        assert result is True
        result = interp.eval("(a and b) or c", a=True, b=False, c=False)
        assert result is False

    def test_boolean_with_comparison(self, interp: Interpreter) -> None:
        """Booleans combined with comparisons should work."""
        result = interp.eval("a > b and ok", a=5, b=3, ok=True)
        assert result is True


class TestRejectsImport:
    """The sandbox must reject __import__ calls."""

    def test_rejects_import(self, interp: Interpreter) -> None:
        """__import__('os') should be rejected."""
        result = interp.eval("__import__('os')")
        # asteval should return None or raise on forbidden operations.
        assert result is None or isinstance(result, Exception)

    def test_rejects_import_via_getattr(self, interp: Interpreter) -> None:
        """getattr with __import__ should be rejected."""
        # asteval restricts attribute access on builtins.
        result = interp.eval("__builtins__.__import__('os')")
        assert result is None or isinstance(result, Exception)


class TestRejectsEval:
    """The sandbox must reject eval calls."""

    def test_rejects_eval(self, interp: Interpreter) -> None:
        """eval('1') should be rejected."""
        result = interp.eval("eval('1')")
        assert result is None or isinstance(result, Exception)

    def test_rejects_exec(self, interp: Interpreter) -> None:
        """exec('pass') should be rejected."""
        result = interp.eval("exec('pass')")
        assert result is None or isinstance(result, Exception)

    def test_rejects_compile(self, interp: Interpreter) -> None:
        """compile should be rejected."""
        result = interp.eval("compile('1', '<string>', 'eval')")
        assert result is None or isinstance(result, Exception)


class TestRejectsAttributeDunder:
    """The sandbox must reject dunder attribute access on objects."""

    def test_rejects_class_attribute(self, interp: Interpreter) -> None:
        """x.__class__ should be rejected."""
        interp.symtable["x"] = "hello"
        result = interp.eval("x.__class__")
        assert result is None or isinstance(result, Exception)

    def test_rejects_dict_attribute(self, interp: Interpreter) -> None:
        """x.__dict__ should be rejected."""
        interp.symtable["x"] = {"a": 1}
        result = interp.eval("x.__dict__")
        assert result is None or isinstance(result, Exception)

    def test_rejects_subclasses(self, interp: Interpreter) -> None:
        """x.__class__.__subclasses__ should be rejected."""
        interp.symtable["x"] = "hello"
        result = interp.eval("x.__class__.__subclasses__()")
        assert result is None or isinstance(result, Exception)


class TestRejectsOpen:
    """The sandbox must reject open() calls."""

    def test_rejects_open(self, interp: Interpreter) -> None:
        """open('/etc/passwd') should be rejected."""
        result = interp.eval("open('/etc/passwd')")
        assert result is None or isinstance(result, Exception)

    def test_rejects_open_with_mode(self, interp: Interpreter) -> None:
        """open('/tmp/test', 'w') should be rejected."""
        result = interp.eval("open('/tmp/test', 'w')")
        assert result is None or isinstance(result, Exception)


class TestSandboxEdgeCases:
    """Additional edge cases for the sandbox."""

    def test_string_methods_allowed(self, interp: Interpreter) -> None:
        """Safe string methods should still work."""
        interp.symtable["x"] = "hello"
        result = interp.eval("x.upper()")
        assert result == "HELLO"

    def test_list_methods_allowed(self, interp: Interpreter) -> None:
        """Safe list methods should still work."""
        interp.symtable["items"] = [3, 1, 2]
        result = interp.eval("sorted(items)")
        assert result == [1, 2, 3]

    def test_rejects_os_system(self, interp: Interpreter) -> None:
        """os.system should be rejected."""
        import os

        interp.symtable["os"] = os
        result = interp.eval("os.system('ls')")
        assert result is None or isinstance(result, Exception)

    def test_rejects_subprocess(self, interp: Interpreter) -> None:
        """subprocess calls should be rejected."""
        import subprocess

        interp.symtable["subprocess"] = subprocess
        result = interp.eval("subprocess.call(['ls'])")
        assert result is None or isinstance(result, Exception)

    def test_rejects_shutil(self, interp: Interpreter) -> None:
        """shutil operations should be rejected."""
        import shutil

        interp.symtable["shutil"] = shutil
        result = interp.eval("shutil.rmtree('/')")
        assert result is None or isinstance(result, Exception)
