"""The Python examples in docs/REFERENCE.md must run (keeps the reference honest)."""

from __future__ import annotations

import re
from pathlib import Path

REFERENCE = Path(__file__).resolve().parents[2] / "docs" / "REFERENCE.md"


def test_reference_python_blocks_execute() -> None:
    blocks = re.findall(r"```python\n(.*?)```", REFERENCE.read_text(), flags=re.S)
    assert len(blocks) >= 8
    namespace: dict[str, object] = {}
    for i, block in enumerate(blocks):
        try:
            exec(compile(block, f"REFERENCE.md block {i}", "exec"), namespace)
        except Exception as e:  # pragma: no cover - failure path
            raise AssertionError(f"REFERENCE.md python block {i} failed: {e!r}\n{block}") from e
