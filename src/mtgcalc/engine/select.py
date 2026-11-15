"""Engine selection (LLD §5.5, ADR-0009).

The native (Rust) engine is used when the optional ``mtgcalc_native`` extension is
installed; otherwise the pure-Python reference engine. Both are exact and must give
identical results (they share one conformance suite). Set ``MTGCALC_ENGINE=python`` to
force the reference engine (for debugging or conformance testing).
"""

from __future__ import annotations

import importlib
import os
from functools import cache
from types import ModuleType

from mtgcalc.engine.base import Engine
from mtgcalc.engine.exact import ExactEngine


@cache
def native_module() -> ModuleType | None:
    """The compiled extension, or ``None`` if it is not installed."""
    try:
        return importlib.import_module("mtgcalc_native")
    except ImportError:
        return None


def native_available() -> bool:
    """Whether the native engine is installed and not disabled by ``MTGCALC_ENGINE``."""
    return os.environ.get("MTGCALC_ENGINE", "auto").lower() != "python" and (
        native_module() is not None
    )


def default_engine() -> Engine:
    """The fastest available exact engine."""
    if native_available():
        from mtgcalc.engine.native import NativeEngine

        return NativeEngine()
    return ExactEngine()
