"""JSON-compatible serialization of public value types (LLD §3.8, NFR-07).

Encoding:
    dataclass -> {"type": ClassName, <field>: <encoded>, ...}
    Fraction  -> {"type": "Fraction", "value": "n/d"}
    frozenset -> {"type": "frozenset", "items": [sorted encoded items]}
    tuple     -> list   (lists decode back to tuples; public types never hold lists)
"""

from __future__ import annotations

import dataclasses
from fractions import Fraction
from typing import Any

from mtgcalc.errors import ValidationError
from mtgcalc.model import conditions, deck, game, mulligan, results, scenario, selectors

_MODULES = (selectors, conditions, deck, game, mulligan, scenario, results)
REGISTRY: dict[str, type[Any]] = {
    name: obj
    for mod in _MODULES
    for name, obj in vars(mod).items()
    if isinstance(obj, type) and dataclasses.is_dataclass(obj) and obj.__module__ == mod.__name__
}


def register(cls: type[Any]) -> type[Any]:
    """Register an additional dataclass for decoding (used by higher layers)."""
    REGISTRY[cls.__name__] = cls
    return cls


def to_dict(obj: Any) -> Any:
    """Encode a value object into JSON-compatible primitives."""
    if isinstance(obj, Fraction):
        return {"type": "Fraction", "value": f"{obj.numerator}/{obj.denominator}"}
    if isinstance(obj, frozenset):
        items = [to_dict(x) for x in obj]
        return {"type": "frozenset", "items": sorted(items, key=repr)}
    if isinstance(obj, tuple | list):
        return [to_dict(x) for x in obj]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out: dict[str, Any] = {"type": type(obj).__name__}
        for f in dataclasses.fields(obj):
            out[f.name] = to_dict(getattr(obj, f.name))
        return out
    if obj is None or isinstance(obj, bool | int | float | str):
        return obj
    raise ValidationError("serialize", f"cannot serialize {type(obj).__name__}")


def from_dict(data: Any) -> Any:
    """Decode the output of :func:`to_dict`."""
    if isinstance(data, list):
        return tuple(from_dict(x) for x in data)
    if isinstance(data, dict):
        kind = data.get("type")
        if kind == "Fraction":
            return Fraction(data["value"])
        if kind == "frozenset":
            return frozenset(from_dict(x) for x in data["items"])
        if not isinstance(kind, str) or kind not in REGISTRY:
            raise ValidationError("deserialize", f"unknown type {kind!r}")
        cls = REGISTRY[kind]
        kwargs = {k: from_dict(v) for k, v in data.items() if k != "type"}
        return cls(**kwargs)
    return data
