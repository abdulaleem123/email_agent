"""DB backups for Super Admin + Celery daily task."""
from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)

BACKUP_KEEP = 14
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "backups")).resolve()


def _is_sqlite() -> bool:
    return (settings.DATABASE_URL or "").startswith("sqlite")


def _sqlite_path():
    url = settings.DATABASE_URL or ""
    if not url.startswith("sqlite"):
        return None
    raw = url.split("sqlite:///")[-1]
    return Path(raw) if raw.startswith("/") else Path(raw).resolve()


def list_backups():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for p in sorted(BACKUP_DIR.glob("chatversio-*.db"), reverse=True):
        try:
            st = p.stat()
            items.append({
                "file": p.name,
                "path": str(p),
                "size_bytes": st.st_size,
                "created_at": datetime.utcfromtimestamp(st.st_mtime).strftime("%Y-%m-%dT%H:%M:%S"),
            })
        except OSError:
            continue
    return items


def _prune(keep=BACKUP_KEEP):
    files = sorted(
        BACKUP_DIR.glob("chatversio-*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for old in files[keep:]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def run_backup():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    if not _is_sqlite():
        logger.info("daily_backup: Postgres — skipped")
        return {
            "ok": True,
            "engine": "postgres",
            "detail": "skipped — infrastructure backups",
            "backups": list_backups(),
        }

    src = _sqlite_path()
    if not src or not src.exists():
        return {
            "ok": False,
            "engine": "sqlite",
            "detail": "sqlite file not found: %s" % src,
            "backups": list_backups(),
        }

    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / ("chatversio-%s.db" % stamp)
    try:
        shutil.copy2(src, dest)
        pruned = _prune(BACKUP_KEEP)
        logger.info("daily_backup: wrote %s (pruned %s)", dest.name, pruned)
        return {
            "ok": True,
            "engine": "sqlite",
            "file": dest.name,
            "path": str(dest),
            "size_bytes": dest.stat().st_size,
            "pruned": pruned,
            "backups": list_backups(),
        }
    except Exception as e:
        logger.exception("daily_backup failed")
        return {
            "ok": False,
            "engine": "sqlite",
            "detail": str(e),
            "backups": list_backups(),
        }