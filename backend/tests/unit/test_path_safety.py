"""File-path containment — a user can't read outside their own session folder.

The download/content endpoints resolve a caller-supplied relative path. These
tests pin the guard in ``api.deps.resolve_owned_file_path`` against the classic
escapes: absolute paths, ``..`` traversal, and cross-user / wrong-session access.
All of these must 403 *before* the filesystem is ever touched.
"""

from __future__ import annotations

import types

import pytest
from fastapi import HTTPException

from app.api.deps import resolve_owned_file_path


def _user(uid: int):
    return types.SimpleNamespace(id=uid)


def _session(sid: str, owner_id: int):
    return types.SimpleNamespace(id=sid, user_id=owner_id)


def test_absolute_path_rejected():
    with pytest.raises(HTTPException) as exc:
        resolve_owned_file_path("/etc/passwd", _user(1), _session("s1", 1))
    assert exc.value.status_code == 403


def test_parent_traversal_rejected():
    with pytest.raises(HTTPException) as exc:
        resolve_owned_file_path("s1/../../etc/passwd", _user(1), _session("s1", 1))
    assert exc.value.status_code == 403


def test_cross_user_access_rejected():
    # Path belongs to session "s1" owned by user 1, but user 2 is asking.
    with pytest.raises(HTTPException) as exc:
        resolve_owned_file_path("s1/POSCAR", _user(2), _session("s1", 1))
    assert exc.value.status_code == 403


def test_wrong_session_prefix_rejected():
    # First path segment must equal the owning session id.
    with pytest.raises(HTTPException) as exc:
        resolve_owned_file_path("other/POSCAR", _user(1), _session("s1", 1))
    assert exc.value.status_code == 403
