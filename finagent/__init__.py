from __future__ import annotations

from pathlib import Path

# Shim: the real package lives at backend/finagent/.
# This file exists solely so `import finagent` resolves to the backend tree.
# Do NOT add sibling modules here — they diverge and become stale dead code.
_backend_package = Path(__file__).resolve().parent.parent / "backend" / "finagent"
__path__ = [str(_backend_package)]
