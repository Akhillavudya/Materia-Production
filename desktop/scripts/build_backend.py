"""Freeze the Materia FastAPI backend into a standalone (onedir) executable.

Part C / C1 — the hardest, riskiest step of the desktop build, so we do it first.
Run this with the project venv's python (the one that has torch/MACE/MatterSim):

    ./venv/bin/python desktop/scripts/build_backend.py

Output: desktop/resources/backend/materia-backend/  (a folder containing the
`materia-backend` executable + all its libraries). The Electron shell launches
that executable directly — no Python install required on the user's machine.

Why onedir (not onefile): the scientific stack is huge (torch, MKL, CUDA libs).
onefile would unpack ~GBs to a temp dir on every launch; onedir starts fast and
is what electron-builder will pack into the installer.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__

# ── Paths ────────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent              # desktop/scripts
DESKTOP = HERE.parent                               # desktop/
REPO = DESKTOP.parent                               # repo root
BACKEND = REPO / "backend"                          # backend/  (where `app` lives)
ENTRY = HERE / "run_backend.py"

DIST = DESKTOP / "resources" / "backend"            # final bundle location
BUILD = DESKTOP / "build" / "pyinstaller"           # scratch workpath
SPEC = BUILD                                         # keep the generated .spec here

# ── Packages whose data files + submodules must be collected wholesale ─────────
# These ship JSON/CSV/yaml data or use dynamic imports that PyInstaller's static
# analysis misses. --collect-all grabs binaries, data, and submodules for each.
COLLECT_ALL = [
    "pymatgen",
    "pymatgen_analysis_defects",
    "ase",
    "mace",
    "mattersim",
    "e3nn",
    "phonopy",
    "phono3py",
    "seekpath",
    "spglib",
    "monty",
    "ruamel",
    "emmet",
    "mp_api",
    "matplotlib",
    "uvicorn",
    "passlib",
    "celery",
    "kombu",
    "google.genai",
]

# Packages that read their own version via importlib.metadata at runtime — without
# the dist-info copied in, that call raises PackageNotFoundError.
COPY_METADATA = [
    "torch",
    "mace_torch",
    "mattersim",
    "e3nn",
    "pymatgen",
    "numpy",
    "ase",
    "tqdm",
    "google-genai",
]

# Dev/observability packages that are NOT used by Materia but get auto-discovered
# (e.g. logfire registers a pydantic plugin) and break in a frozen binary. Excluding
# them shrinks the bundle and removes the source-inspection crash at startup.
EXCLUDE_MODULES = [
    "logfire",
    "IPython",
    "pytest",
]

# Modules imported dynamically (by name/string) that static analysis won't see.
HIDDEN_IMPORTS = [
    "app.main",
    "aiosqlite",
    "asyncpg",
    "psycopg2",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "anyio._backends._asyncio",
]


def main() -> int:
    if not ENTRY.exists():
        print(f"ERROR: entry script missing: {ENTRY}", file=sys.stderr)
        return 2

    # Clean previous output so a stale bundle can't mask a broken build.
    for d in (DIST / "materia-backend", BUILD):
        if d.exists():
            shutil.rmtree(d)
    DIST.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)

    args: list[str] = [
        str(ENTRY),
        "--name", "materia-backend",
        "--onedir",
        "--noconfirm",
        "--console",
        "--paths", str(BACKEND),          # so `import app...` resolves
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(SPEC),
        # bundle the migrations in case we ever want alembic on desktop (cheap)
        "--add-data", f"{BACKEND / 'alembic.ini'}{os.pathsep}.",
    ]
    for pkg in COLLECT_ALL:
        args += ["--collect-all", pkg]
    for pkg in COPY_METADATA:
        args += ["--copy-metadata", pkg]
    for mod in HIDDEN_IMPORTS:
        args += ["--hidden-import", mod]
    for mod in EXCLUDE_MODULES:
        args += ["--exclude-module", mod]

    print("[build_backend] PyInstaller args:\n  " + " ".join(args), flush=True)
    PyInstaller.__main__.run(args)

    exe = DIST / "materia-backend" / "materia-backend"
    print("\n[build_backend] done.")
    print(f"[build_backend] executable: {exe}")
    print("[build_backend] smoke test it with:")
    print(f"    MATERIA_PORT=8123 ENV=development JOB_BACKEND=inline {exe}")
    return 0 if exe.exists() else 1


if __name__ == "__main__":
    raise SystemExit(main())
