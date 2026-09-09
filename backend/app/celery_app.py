from celery import Celery
from .config import settings

celery = Celery("chatversio_crm", broker=settings.REDIS_URL,
                backend=settings.REDIS_URL, include=["app.tasks"])

celery.conf.update(
    task_serializer="json", accept_content=["json"], result_serializer="json",
    timezone="UTC", task_acks_late=True, worker_max_tasks_per_child=200,
    broker_connection_retry_on_startup=True,
)

celery.conf.beat_schedule = {
    "poll-inbox-every-2-min": {"task": "app.tasks.poll_inbox", "schedule": 120.0},
    "followup-sweep-hourly": {"task": "app.tasks.followup_sweep", "schedule": 3600.0},
    "purge-garbage-daily": {"task": "app.tasks.purge_garbage", "schedule": 86400.0},
    "daily-db-backup": {"task": "app.tasks.daily_backup", "schedule": 86400.0},
}