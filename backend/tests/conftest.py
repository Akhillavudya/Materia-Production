"""Top-level pytest config for the Materia backend test net (Step 9).

Ensures ``import app...`` resolves no matter where pytest is invoked from, and
keeps the test environment in *development* mode (so the production fail-fast
guards in ``core.config`` don't trip during ordinary unit tests — the
production-mode behaviour is exercised explicitly in ``tests/unit/test_config.py``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# backend/ root = parent of this file's directory (tests/conftest.py → backend/).
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# Force development mode for the default test run; never inherit a stray ENV.
os.environ.setdefault("ENV", "development")
