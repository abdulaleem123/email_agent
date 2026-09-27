"""Background job runner for the long operations the UI must not wait on.

Uploading an 80k-row sheet, or MX-verifying 20k mailboxes, takes minutes. Done
inside the request it would hit the proxy timeout, hold a DB connection the
whole time, and surface as a 500 with the work half-done. So those endpoints
enqueue here and return 202 + a job id, and the page polls ImportJob for the
progress bar.

Why a thread pool and not Celery: imports must work on a single-box install
where nobody started a worker. Celery is still used for the send pipeline (it
has to survive restarts); for imports a bounded pool inside the API process is
enough, and the STATE lives in Postgres, not in memory — so several API workers
or a page refresh see the same job, and a result survives a restart.

Guards that matter at volume:
- MAX_CONCURRENT jobs at a time; extras queue instead of thrashing the DB.
- One job row update per chunk (never per row) — progress writes are cheap.
- Any exception is recorded on the job, never raised into a request.
"""
import json
import logging
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from sqlalchemy import text

from ..database import SessionLocal
from .. import models
from ..config import settings

log = logging.getLogger("chatversio.jobs")

MAX_CONCURRENT = max(1, int(getattr(settings, "IMPORT_MAX_CONCURRENT", 2) or 2))
POOL = ThreadPoolExecutor(max_workers=MAX_CONCURRENT,
                          thread_name_prefix="import-job")

# A job is "stalled" if nothing touched it for this long (process died
# mid-import). Swept so the UI never shows a frozen 40% bar forever.
STALE_AFTER_MINUTES = 30


def _sess():
    return SessionLocal()


def create_job(**fields) -> int:
    db = _sess()
    try:
        job = models.ImportJob(**fields)
        db.add(job)
        db.commit()
        return job.id
    finally:
        db.close()


def update_job(job_id: int, **fields) -> None:
    """Progress write. Deliberately swallows its own errors: losing a progress
    tick must never kill an import that is otherwise fine.

    One SELECT for the row, not one per field — this runs once per 1 000 rows
    and a per-field get() turned a single progress write into N queries."""
    db = _sess()
    try:
        j = db.get(models.ImportJob, job_id)
        if not j:
            return
        for k, v in fields.items():
            setattr(j, k, v)
        j.updated_at = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def get_job(job_id: int) -> dict | None:
    db = _sess()
    try:
        j = db.get(models.ImportJob, job_id)
        if not j:
            return None
        return job_to_dict(j)
    finally:
        db.close()


def job_to_dict(j: models.ImportJob) -> dict:
    result = None
    if j.result_json:
        try:
            result = json.loads(j.result_json)
        except Exception:
            result = None
    return {
        "id": j.id, "kind": j.kind, "filename": j.filename, "source": j.source,
        "status": j.status, "phase": j.phase, "pct": j.pct,
        "total": j.total, "processed": j.processed,
        "created": j.created_count, "skipped_duplicates": j.skipped_count,
        "cross_duplicates": j.cross_dup_count,
        "blocked_addresses": j.blocked_count, "unverified": j.unverified_count,
        "batch_size": j.batch_size, "campaign_id": j.campaign_id,
        "agent_id": j.agent_id, "auto_enrolled": bool(j.auto_enroll),
        "upload_tag": j.upload_tag, "error": j.error or "", "result": result,
        "created_at": j.created_at.isoformat() if j.created_at else "",
        "updated_at": j.updated_at.isoformat() if j.updated_at else "",
    }


def recent_jobs(kind: str | None = None, limit: int = 8) -> list[dict]:
    db = _sess()
    try:
        q = db.query(models.ImportJob)
        if kind:
            q = q.filter(models.ImportJob.kind == kind)
        rows = (q.order_by(models.ImportJob.id.desc())
                 .limit(max(1, min(limit, 50))).all())
        return [job_to_dict(j) for j in rows]
    finally:
        db.close()


def clear_finished_jobs(keep: int = 20) -> int:
    """Housekeeping: drop old finished receipts, keep the newest few.

    Deleted in chunks — a 50k-row `.in_(ids)` would exceed Postgres' bind
    parameter limit and raise, leaving the table to grow forever."""
    db = _sess()
    try:
        ids = [i for (i,) in db.query(models.ImportJob.id)
               .filter(models.ImportJob.status.in_(("done", "error", "cancelled")))
               .order_by(models.ImportJob.id.desc()).offset(keep).all()]
        n = 0
        for i in range(0, len(ids), 1000):
            n += (db.query(models.ImportJob)
                  .filter(models.ImportJob.id.in_(ids[i:i + 1000]))
                  .delete(synchronize_session=False))
        db.commit()
        return n
    finally:
        db.close()


def sweep_stalled() -> int:
    """After a crash/restart a job can be left 'queued' or 'running' with
    nobody working on it. Mark those failed so the UI stops waiting and the
    lead is importable again (every insert was already committed per chunk).
    'queued' is included on purpose: a job that never got a pool slot is just
    as dead once the process is gone, and it would otherwise sit at 1% forever."""
    db = _sess()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=STALE_AFTER_MINUTES)
        n = (db.query(models.ImportJob)
             .filter(models.ImportJob.status.in_(("queued", "running")),
                     models.ImportJob.updated_at < cutoff)
             .update({"status": "error",
                      "error": "Import was interrupted (server restarted). "
                               "Re-upload the file — anything already imported "
                               "is safe, duplicates are skipped."},
                     synchronize_session=False))
        db.commit()
        return n
    finally:
        db.close()


def fail_running_on_boot() -> int:
    """At startup, EVERY unfinished job is dead: this process has a brand new
    thread pool, so nothing can still be driving a job row that says
    'running'. Waiting 30 minutes for the age-based sweep would leave a
    restored backup showing a fake progress bar, so nuke them immediately."""
    db = _sess()
    try:
        n = (db.query(models.ImportJob)
             .filter(models.ImportJob.status.in_(("queued", "running")))
             .update({"status": "error",
                      "error": "Import was interrupted (server restarted). "
                               "Re-upload the file — anything already imported "
                               "is safe, duplicates are skipped."},
                     synchronize_session=False))
        db.commit()
        return n
    finally:
        db.close()


def is_cancelled(job_id: int) -> bool:
    """Cheap poll so a long import stops promptly when the user cancels."""
    db = _sess()
    try:
        status = db.query(models.ImportJob.status)\
                   .filter(models.ImportJob.id == job_id).scalar()
        return status == "cancelled"
    except Exception:
        return False
    finally:
        db.close()


def submit(job_id: int, fn, *args, **kwargs) -> None:
    """Run `fn(job_id, *args)` in the pool, tracking status + errors for us."""
    def runner():
        db = _sess()
        try:
            j = db.get(models.ImportJob, job_id)
            if not j:
                return
            if j.status == "cancelled":
                return
            j.status = "running"
            j.updated_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()
        try:
            fn(job_id, *args, **kwargs)
        except Exception as e:                      # never reach the request
            log.error("import job %s failed: %s\n%s", job_id, e, traceback.format_exc())
            update_job(job_id, status="error",
                       phase=f"Failed: {e}"[:300], error=str(e)[:2000], pct=100)
        finally:
            sweep_stalled()

    POOL.submit(runner)


def wait_for_slot() -> None:
    """Optional back-pressure helper for callers that want to block politely."""
    _ = POOL


_COUNTABLE = {"leads", "email_messages", "import_jobs", "campaigns",
              "agents", "pitch_records", "template_uses"}


def raw_count(table: str) -> int:
    """Cheap row count for capacity display; never raises.

    Whitelisted rather than interpolated blind — this builds SQL and the table
    name should never come from a request."""
    if table not in _COUNTABLE:
        return -1
    db = _sess()
    try:
        return db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
    except Exception:
        return -1
    finally:
        db.close()


# Mark leftovers from a previous process as failed at import time, so a dead
# job never shows a permanent "processing…" bar on the Leads page.
def bootstrap() -> None:
    try:
        n = fail_running_on_boot() + sweep_stalled()
        if n:
            log.info("marked %s stalled import job(s) as failed", n)
        clear_finished_jobs()
    except Exception:
        log.debug("job bootstrap skipped", exc_info=True)


_bootstrap_lock = threading.Lock()
_bootstrapped = False


def ensure_bootstrap() -> None:
    global _bootstrapped
    with _bootstrap_lock:
        if _bootstrapped:
            return
        _bootstrapped = True
        bootstrap()
