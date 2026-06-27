"""Frozen entry point for the Materia desktop backend.

This is the script PyInstaller turns into the `materia-backend` executable. It is
*not* used in dev (there you run uvicorn directly) — it exists so the bundled app
has a single, import-clean entry that:

  1. reads host/port from the environment (the Electron shell picks a free port),
  2. starts uvicorn against the EXISTING FastAPI app (`app.main:app`),

The app's own startup hook calls `Base.metadata.create_all`, so the local SQLite
schema is created on first boot — no alembic step is needed on the desktop.

Environment (set by the Electron `backend.js`):
  MATERIA_HOST   bind address           (default 127.0.0.1)
  MATERIA_PORT   bind port              (required in production; default 8000 here)
  plus the usual backend env: ENV, ENABLE_HEAVY_TOOLS, JOB_BACKEND, DB_PATH,
  PRE_TRAINED_MODELS_DIR, STORAGE_ROOT, JWT_SECRET_KEY, FIELD_ENCRYPTION_KEY, ...
"""

import os
import sys

# Disable pydantic plugins BEFORE anything imports pydantic. A frozen binary has no
# .py source on disk, and some installed plugins (e.g. logfire) call inspect.getsource()
# at startup, which raises "OSError: could not get source code" and kills the process.
# Materia uses no pydantic plugins, so turning them off is safe and makes the freeze robust.
os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "1")


def main() -> int:
    host = os.environ.get("MATERIA_HOST", "127.0.0.1")
    port = int(os.environ.get("MATERIA_PORT", "8000"))

    # Import lazily so any import error is reported on stderr (the shell captures it).
    import uvicorn

    from app.main import app

    print(f"[materia-backend] starting uvicorn on {host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
