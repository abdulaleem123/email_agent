from celery import Celery
from .config import settings

celery = Celery("chatversio_crm", broker=settings.REDIS_URL,
                backend=settings.REDIS_URL, include=["app.tasks"])

celery.conf.update(
    task_serializer="json", accept_content=["json"], result_serializer="json",
    timezone="UTC", task_acks_late=True, worker_max_tasks_per_child=200,
    broker_connection_retry_on_startup=True,
    # 80k leads = ~1 600 batch tasks, each sleeping between sends. Without
    # prefetch the worker grabs thousands at once and the queue collapses;
    # without visibility_timeout a long batch gets redelivered while running.
    worker_prefetch_multiplier=1,
    task_visibility_timeout=60 * 60 * 12,
    broker_transport_options={"visibility_timeout": 60 * 60 * 12},
    task_time_limit=60 * 60 * 6,
    task_soft_time_limit=60 * 60 * 5,
)

celery.conf.beat_schedule = {
    "poll-inbox-every-2-min": {"task": "app.tasks.poll_inbox", "schedule": 120.0},
    "followup-sweep-hourly": {"task": "app.tasks.followup_sweep", "schedule": 3600.0},
    "purge-garbage-daily": {"task": "app.tasks.purge_garbage", "schedule": 86400.0},
    # Audit trail retention (24h) — hourly so it also trims when no admin
    # action happens at all. See app/audit.py.
    "purge-audit-logs-hourly": {"task": "app.tasks.purge_audit_logs", "schedule": 3600.0},
    "purge-escalations-daily": {"task": "app.tasks.purge_escalations", "schedule": 86400.0},
    "stale-leads-sweep-daily": {"task": "app.tasks.stale_leads_sweep", "schedule": 86400.0},
    "daily-db-backup": {"task": "app.tasks.daily_backup", "schedule": 86400.0},
}