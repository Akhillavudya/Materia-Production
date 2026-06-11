import os
import re
import shutil
from pathlib import Path

# absolute path — never depends on the CWD the server was started from
STORAGE_ROOT = Path(__file__).resolve().parent.parent / "storage" / "runs"

# ── allowed upload extensions ─────────────────────────────────────────────────
# VASP files have no extension — handled by name check
ALLOWED_UPLOAD_NAMES = {
    'POSCAR', 'CONTCAR', 'INCAR', 'KPOINTS', 'POTCAR',
    'OUTCAR', 'OSZICAR', 'XDATCAR', 'CHGCAR', 'WAVECAR',
}
ALLOWED_UPLOAD_EXTENSIONS = {
    '.cif', '.xyz', '.txt', '.log', '.json', '.csv',
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

# add to app/services/file_service.py

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

