"""Database backups. Runs daily via Celery beat (see tasks.daily_backup) and
can also be run manually: `python -m app.services.backup`.

- SQLite: uses sqlite3's online backup API (safe to run against a live DB —
  it doesn't just copy bytes off disk, which can corrupt a WAL-mode DB mid-write).
- Postgres: shells out to `pg_dump` if it's on PATH.

Backups land in BACKUP_DIR (default ./backups) as timestamped files;
retention keeps the newest BACKUP_KEEP (default 14) and deletes older ones.
"""
import os
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from ..config import settings

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "./backups"))
BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "14"))


def _sqlite_path() -> str:
    # sqlite:///./chatversio.db -> ./chatversio.db
    return settings.DATABASE_URL.split("sqlite:///", 1)[-1]


def run_backup() -> dict:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")

    if settings.DATABASE_URL.startswith("sqlite"):
        src_path = _sqlite_path()
        if not os.path.exists(src_path):
            return {"ok": False, "detail": f"SQLite file not found: {src_path}"}
        dest_path = BACKUP_DIR / f"chatversio-{stamp}.db"
        src = sqlite3.connect(src_path)
        dest = sqlite3.connect(str(dest_path))
        with dest:
            src.backup(dest)          # online backup API — safe on a live DB
        src.close()
        dest.close()
        result = {"ok": True, "file": str(dest_path), "engine": "sqlite"}

    elif settings.DATABASE_URL.startswith("postgres"):
        dest_path = BACKUP_DIR / f"chatversio-{stamp}.sql"
        try:
            with open(dest_path, "wb") as f:
                subprocess.run(["pg_dump", settings.DATABASE_URL], stdout=f, check=True, timeout=600)
            result = {"ok": True, "file": str(dest_path), "engine": "postgres"}
        except FileNotFoundError:
            return {"ok": False, "detail": "pg_dump not found on PATH — install postgresql-client"}
        except subprocess.CalledProcessError as e:
            return {"ok": False, "detail": f"pg_dump failed: {e}"}
    else:
        return {"ok": False, "detail": f"Unrecognized DATABASE_URL scheme: {settings.DATABASE_URL}"}

    _cleanup_old_backups()
    return result


def _cleanup_old_backups():
    files = sorted(BACKUP_DIR.glob("chatversio-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[BACKUP_KEEP:]:
        try:
            old.unlink()
        except OSError:
            pass


def list_backups() -> list[dict]:
    if not BACKUP_DIR.exists():
        return []
    files = sorted(BACKUP_DIR.glob("chatversio-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"file": f.name, "size_bytes": f.stat().st_size,
            "created_at": datetime.utcfromtimestamp(f.stat().st_mtime).isoformat()} for f in files]


# --- restore steps (documented here since a restore is deliberate, not automated) ---
# SQLite:
#   1. Stop the backend (and Celery worker/beat).
#   2. cp backups/chatversio-<timestamp>.db ./chatversio.db
#   3. Restart the backend — migrate.py will no-op since the schema already matches.
# Postgres:
#   1. Stop the backend.
#   2. psql $DATABASE_URL < backups/chatversio-<timestamp>.sql
#   3. Restart the backend.

if __name__ == "__main__":
    print(run_backup())