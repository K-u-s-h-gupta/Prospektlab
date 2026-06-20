"""Sandboxed Python tool for deterministic financial computation.

The LLM writes assumptions and formulas; the sandbox executes them safely and
returns structured numerical results. This eliminates hallucinated DCF/valuation
numbers.
"""

from __future__ import annotations

import ast
import logging
import math
import multiprocessing
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("finagent.tools.sandbox")


# Safe builtins allowed in the sandbox
_ALLOWED_BUILTINS = {
    "abs", "round", "max", "min", "sum", "len", "range", "zip", "enumerate",
    "float", "int", "str", "bool", "dict", "list", "tuple", "set",
}

_ALLOWED_MATH = {
    "sqrt", "log", "exp", "pow", "floor", "ceil", "pi", "e",
    "sin", "cos", "tan", "sinh", "cosh", "tanh",
}


class SandboxError(Exception):
    pass


@dataclass
class SandboxResult:
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": self.output,
            "logs": self.logs,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
        }


def _safe_exec_worker(code: str, inputs: dict[str, Any], queue: multiprocessing.Queue) -> None:
    """Worker running in a separate process."""
    t0 = time.perf_counter()
    logs: list[str] = []
    try:
        # Validate AST
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                raise SandboxError("Imports are not allowed in sandbox.")
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id not in _ALLOWED_BUILTINS and func.id not in _ALLOWED_MATH:
                    raise SandboxError(f"Function '{func.id}' is not allowed.")

        # Prepare safe namespace
        safe_math = {name: getattr(math, name) for name in _ALLOWED_MATH if hasattr(math, name)}
        safe_builtins = {name: __builtins__[name] for name in _ALLOWED_BUILTINS if name in __builtins__}  # type: ignore
        namespace = {
            "__builtins__": safe_builtins,
            "math": safe_math,
            "inputs": inputs,
        }
        exec(code, namespace)  # noqa: S102
        output = namespace.get("OUTPUT", {})
        queue.put(SandboxResult(success=True, output=output, logs=logs, elapsed_ms=int((time.perf_counter() - t0) * 1000)))
    except Exception as exc:
        queue.put(SandboxResult(success=False, error=f"{type(exc).__name__}: {exc}", logs=logs, elapsed_ms=int((time.perf_counter() - t0) * 1000)))


class SandboxTool:
    """Execute Python code in a separate process with timeout and resource limits."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    def run(self, code: str, inputs: dict[str, Any] | None = None) -> SandboxResult:
        """Run code in a sandboxed process."""
        code = self._sanitize(code)
        inputs = inputs or {}
        queue: multiprocessing.Queue = multiprocessing.Queue()
        process = multiprocessing.Process(target=_safe_exec_worker, args=(code, inputs, queue))
        process.start()
        process.join(timeout=self.timeout_seconds)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
            return SandboxResult(success=False, error="Sandbox execution timed out")
        try:
            result = queue.get(timeout=1.0)
            return result
        except Exception as exc:
            return SandboxResult(success=False, error=f"Failed to read sandbox result: {exc}")

    def _sanitize(self, code: str) -> str:
        # Remove dangerous constructs
        code = re.sub(r"\b__\w+__\b", "", code)
        code = re.sub(r"\bimport\b", "", code)
        code = re.sub(r"\bexec\b|\beval\b", "", code)
        return code


__all__ = ["SandboxTool", "SandboxResult", "SandboxError"]
