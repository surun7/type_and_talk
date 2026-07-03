# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Type & Talk authors
#
"""Variable context for skill execution — stores inputs, intermediate results,
and provides template rendering with ``{{ dotted.path }}`` substitution."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple, Union


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class SkillContextError(Exception):
    """Raised on context-related errors (missing variable, bad path, etc.)."""


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


class SkillContext:
    """Holds the variable scope for a single skill run.

    Supports setting/getting named values, storing step results, and
    rendering ``{{ dotted.path }}`` templates from nested dictionaries.
    """

    def __init__(self, inputs: Dict[str, Any]) -> None:
        self._vars: Dict[str, Any] = dict(inputs)
        self._step_results: Dict[str, Dict[str, Any]] = {}

    # ---- plain variables ----

    def set(self, name: str, value: Any) -> None:
        """Store *value* under *name*."""
        self._vars[name] = value

    def get(self, name: str) -> Any:
        """Retrieve a value by *name*.

        Raises :class:`SkillContextError` if not found.
        """
        try:
            return self._vars[name]
        except KeyError:
            raise SkillContextError(f"Variable {name!r} is not set")

    # ---- step results ----

    def set_step_result(self, step_id: str, result: Dict[str, Any]) -> None:
        """Store the result dictionary produced by a step."""
        self._step_results[step_id] = result

    def get_step_result(self, step_id: str) -> Dict[str, Any] | None:
        """Retrieve a previously stored step result, or ``None``."""
        return self._step_results.get(step_id)

    # ---- template rendering ----

    _TEMPLATE_RE = re.compile(r"\{\{\s*([^\s{}]+)\s*\}\}")

    def render(self, template: str) -> str:
        """Substitute ``{{ dotted.path.references }}`` with values from the
        context variables and step results.

        References are resolved in the following order:
        1. Step results (``step.<step_id>.<path>``)
        2. Context variables (``<name>``)

        Nested paths use dots, e.g. ``{{ output.status }}`` looks up
        ``_vars["output"]["status"]``.

        Raises :class:`SkillContextError` when a path cannot be resolved.
        """
        def _resolve_path(path: str) -> str:
            parts = path.split(".")
            # Step-result prefixed path → step.<step_id>.<rest...>
            if parts[0] == "step" and len(parts) >= 2:
                step_id = parts[1]
                result = self._step_results.get(step_id)
                if result is None:
                    raise SkillContextError(
                        f"No result for step {step_id!r} when resolving {path!r}"
                    )
                obj: Any = result
                for key in parts[2:]:
                    if isinstance(obj, dict) and key in obj:
                        obj = obj[key]
                    else:
                        raise SkillContextError(
                            f"Cannot resolve {path!r}: "
                            f"{key!r} not found in step {step_id!r} result"
                        )
                return self._to_str(obj)
            # Plain variable path
            obj = self._vars
            for key in parts:
                if isinstance(obj, dict) and key in obj:
                    obj = obj[key]
                else:
                    raise SkillContextError(
                        f"Cannot resolve {path!r}: {key!r} not found in context"
                    )
            return self._to_str(obj)

        result: List[str] = []
        last_end = 0
        for m in self._TEMPLATE_RE.finditer(template):
            result.append(template[last_end : m.start()])
            result.append(_resolve_path(m.group(1).strip()))
            last_end = m.end()
        result.append(template[last_end:])
        return "".join(result)

    def render_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Deep-walk *args*, rendering every string leaf through
        :meth:`render`. Dicts and lists are traversed recursively."""

        def _walk(value: Any) -> Any:
            if isinstance(value, str):
                return self.render(value)
            elif isinstance(value, dict):
                return {k: _walk(v) for k, v in value.items()}
            elif isinstance(value, (list, tuple)):
                return [_walk(item) for item in value]
            return value

        return {k: _walk(v) for k, v in args.items()}

    # ---- helpers ----

    @staticmethod
    def _to_str(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (int, float, bool)):
            return str(value).lower() if isinstance(value, bool) else str(value)
        if isinstance(value, str):
            return value
        return str(value)
