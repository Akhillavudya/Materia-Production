import os
import re
import shutil
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

# absolute path — never depends on the CWD the server was started from.
# This module lives at app/services/storage/, so the app root is two parents up
# (storage → services → app); storage data lives at app/storage/runs.
STORAGE_ROOT = Path(__file__).resolve().parents[2] / "storage" / "runs"

# ── allowed upload extensions ─────────────────────────────────────────────────
# VASP files have no extension — handled by name check
ALLOWED_UPLOAD_NAMES = {
    'POSCAR', 'CONTCAR', 'INCAR', 'KPOINTS', 'POTCAR',
    'OUTCAR', 'OSZICAR', 'XDATCAR', 'CHGCAR', 'WAVECAR',
}
ALLOWED_UPLOAD_EXTENSIONS = {
    # structure formats (pymatgen/ASE-readable) — U2/U3: .vasp was missing before
    '.cif', '.xyz', '.vasp', '.poscar', '.contcar', '.cssr',
    '.pwscf', '.in', '.pdb', '.xsf', '.res', '.gen',
    # text / data
    '.txt', '.log', '.json', '.csv',
}
# extensions that are always rejected for safety
BLOCKED_EXTENSIONS = {
    '.exe', '.bin', '.so', '.dylib', '.dll', '.bat',
    '.cmd', '.ps1', '.py', '.sh', '.bash', '.zsh',
}


def get_session_dir(session_id: str) -> Path:
    """Return the absolute session folder path, creating it if needed."""
    folder = STORAGE_ROOT / session_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder.resolve()


def get_upload_dir(session_id: str) -> Path:
    """Return the uploads subfolder inside the session folder."""
    folder = STORAGE_ROOT / session_id / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def sanitize_filename(name: str) -> str:
    """
    Strip path components and dangerous characters from a filename.
    Only keeps alphanumerics, dots, underscores, hyphens.
    Prevents path traversal like ../../etc/passwd
    """
    # take only the basename — strips any directory components
    name = Path(name).name
    # remove any character that isn't safe
    name = re.sub(r'[^\w.\-]', '_', name)
    # strip leading dots to prevent hidden file tricks
    name = name.lstrip('.')
    return name or "uploaded_file"


def is_upload_allowed(filename: str) -> bool:
    """
    Check if a file is allowed to be uploaded.
    Returns True if safe, False if rejected.
    """
    name_upper = Path(filename).name.upper()
    ext        = Path(filename).suffix.lower()

    # block dangerous extensions first — always
    if ext in BLOCKED_EXTENSIONS:
        return False

    # allow known VASP filenames with no extension
    if name_upper in ALLOWED_UPLOAD_NAMES:
        return True

    # allow VASP structure files named with a suffix, e.g. POSCAR_initial,
    # POSCAR_final, CONTCAR_relaxed (common when supplying two NEB endpoints).
    if name_upper.startswith(("POSCAR", "CONTCAR")):
        return True

    # allow known safe extensions
    if ext in ALLOWED_UPLOAD_EXTENSIONS:
        return True

    # reject anything else
    return False


def list_session_files(session_id: str) -> list[dict]:
    """Return metadata for every file in the session folder."""
    folder = STORAGE_ROOT / session_id
    if not folder.exists():
        return []

    files = []
    for f in sorted(folder.rglob("*")):
        if f.is_file():
            rel = f.relative_to(STORAGE_ROOT)
            files.append({
                "name":     f.name,
                "size_kb":  round(f.stat().st_size / 1024, 2),
                "rel_path": str(rel),
            })
    return files


def list_new_files(session_id: str, since_timestamp: float) -> list[dict]:
    """
    Return only files created AFTER since_timestamp.
    Used to scope file results to the current tool call only.
    """
    folder = STORAGE_ROOT / session_id
    if not folder.exists():
        return []

    files = []
    for f in sorted(folder.rglob("*")):
        if f.is_file() and f.stat().st_mtime >= since_timestamp:
            rel = f.relative_to(STORAGE_ROOT)
            files.append({
                "name":     f.name,
                "size_kb":  round(f.stat().st_size / 1024, 2),
                "rel_path": str(rel),
            })
    return files


def save_text_file(session_id: str, filename: str, content: str) -> Path:
    """Write a text file into the session folder."""
    folder = get_session_dir(session_id)
    path   = folder / filename
    path.write_text(content)
    return path

def find_best_poscar(session_dir: str) -> str | None:
    """
    Find POSCAR strictly within THIS session's directory only.
    Never reads from other sessions.
    Priority: root POSCAR > named POSCAR_* in root > subdirectory POSCAR
    Excludes _temp files.
    """
    session_path = Path(session_dir)
    if not session_path.exists():
        return None

    # 1. exact POSCAR in session root — most recently generated "current" structure
    root_poscar = session_path / "POSCAR"
    if root_poscar.exists():
        return str(root_poscar)

    # 2. named POSCAR_* directly in session root (not in subdirs)
    root_named = sorted(
        [
            f for f in session_path.iterdir()
            if f.is_file()
            and f.name.startswith("POSCAR")
            and "temp" not in f.name.lower()
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if root_named:
        return str(root_named[0])

    # 3. any POSCAR anywhere in session (subdirs) — excluding temp files
    all_poscars = sorted(
        [
            f for f in session_path.rglob("POSCAR*")
            if f.is_file() and "temp" not in f.name.lower()
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if all_poscars:
        return str(all_poscars[0])

    return None


# ── Request-scoped session directory (ContextVar) ─────────────────────────────
# The agent sets this per coroutine before each tool call so tools resolve files
# against the right session without threading the id through every signature.
# Safe under concurrent async requests; the executor thread re-sets it explicitly.

_session_dir_var: ContextVar[str] = ContextVar("session_dir", default="")


def session_dir() -> Path:
    """Resolve the current request's session storage directory."""
    d = _session_dir_var.get()
    if d:
        p = Path(d)
        p.mkdir(parents=True, exist_ok=True)
        return p
    return Path.cwd()


def set_session_dir(path: str):
    """Bind the current coroutine/thread to a session directory."""
    return _session_dir_var.set(path)


# ── Shared structure / file resolution (used by tools and the files API) ──────

TEXT_EXTENSIONS = {"", ".txt", ".log", ".csv", ".json", ".xml", ".cif", ".xyz", ".html"}
VASP_TEXT_NAMES = {"POSCAR", "CONTCAR", "INCAR", "KPOINTS", "POTCAR",
                   "OSZICAR", "OUTCAR", "XDATCAR"}


def session_path() -> Path:
    """Absolute, resolved path of the current request's session directory."""
    return session_dir().resolve()


def rel_to_storage(path: Path) -> str:
    """Return `path` relative to STORAGE_ROOT, or just its name if outside."""
    try:
        return str(path.resolve().relative_to(STORAGE_ROOT.resolve()))
    except ValueError:
        return str(path.name)


def safe_file_in_session(name: str) -> Path:
    """Resolve a file within the current session, rejecting traversal.

    `name` may be a session-relative path, an absolute path inside the session,
    or "auto"/"" to select the most-recently-modified file.
    """
    base = session_path()
    requested = "auto" if name in ("", None) else str(name)

    if requested == "auto":
        candidates = sorted(
            [p for p in base.rglob("*") if p.is_file()],
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if not candidates:
            raise FileNotFoundError("No files exist in this session yet.")
        return candidates[0]

    rel = Path(requested)

    # Absolute paths are allowed only if they resolve inside the session dir.
    if rel.is_absolute():
        try:
            rel.resolve().relative_to(base)
        except ValueError:
            raise PermissionError("File path must stay inside the current session.")
        if rel.exists() and rel.is_file():
            return rel.resolve()
        raise FileNotFoundError(f"File '{rel.name}' was not found in this session.")

    if ".." in rel.parts:
        raise PermissionError("File path must stay inside the current session.")

    direct = (base / rel).resolve()
    if direct.exists() and direct.is_file():
        direct.relative_to(base)
        return direct

    matches = [p for p in base.rglob(rel.name) if p.is_file()]
    if matches:
        return sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)[0]

    raise FileNotFoundError(f"File '{requested}' was not found in this session.")


def find_structure_in_session(name: Optional[str], prefer_contcar: bool = False) -> Path:
    """Locate a POSCAR / CONTCAR in the current session directory.

    The single shared resolver used by `optimize_structure` (prefer POSCAR) and
    `run_md_simulation` (prefer the relaxed CONTCAR).
    """
    base = session_path()

    if name:
        direct = (base / name).resolve()
        if direct.exists() and direct.is_file():
            return direct
        matches = [p for p in base.rglob(name) if p.is_file()]
        if matches:
            return sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)[0]
        raise FileNotFoundError(
            f"File '{name}' not found in this session. "
            "Generate VASP inputs (or run an optimization) first."
        )

    candidates = ("CONTCAR", "POSCAR") if prefer_contcar else ("POSCAR", "CONTCAR")
    for candidate in candidates:
        p = base / candidate
        if p.exists():
            return p

    poscar_files = sorted(
        [p for p in base.rglob("POSCAR*") if p.is_file()],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if poscar_files:
        return poscar_files[0]

    vasp_files = sorted(
        [p for p in base.rglob("*.vasp") if p.is_file()],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if vasp_files:
        return vasp_files[0]

    all_files = sorted(
        [p for p in base.rglob("*") if p.is_file()],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if all_files:
        return all_files[0]

    raise FileNotFoundError(
        "No structure file found in this session. Generate VASP inputs first."
    )

