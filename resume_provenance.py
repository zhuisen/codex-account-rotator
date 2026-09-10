"""Immutable proxy-session markers; never modify Codex's database or rollouts.

Each empty file is a fact keyed by canonical CODEX_HOME and session UUID. Exclusive
creation is atomic on macOS and Windows: no shared JSON rewrite or additional lock
order is needed. Keep markers after exit because anonymous proxy telemetry persists.
"""
import hashlib
import os
import stat
from pathlib import Path
from uuid import UUID


def marker_path(store, codex_home, session_id):
    identity = str(UUID(session_id))
    home = os.path.normcase(str(Path(codex_home).expanduser().resolve()))
    key = hashlib.sha256(home.encode("utf-8")).hexdigest()
    return Path(store) / ".proxy-sessions-v1" / key / identity


def is_proxy_session(store, codex_home, session_id):
    """False means absent; invalid/unreadable state raises so callers refuse attribution."""
    path = marker_path(store, codex_home, session_id)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(mode):
        raise OSError("Invalid proxy session marker")
    return True


def mark_proxy_session(store, codex_home, session_id):
    path = marker_path(store, codex_home, session_id)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if not is_proxy_session(store, codex_home, session_id):
            raise OSError("Proxy session marker disappeared")
        return
    os.close(fd)
