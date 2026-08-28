"""Lightweight additive migrations for SQLite/Postgres (adds new columns if
the DB predates them). Real prod: use Alembic."""
from sqlalchemy import inspect, text
from .database import engine

ADDITIVE = {
    "notifications": [
        ("agent_id", "INTEGER"),
    ],
    "agents": [
        ("role", "VARCHAR(120) DEFAULT ''"),
        ("persona_prompt", "TEXT DEFAULT ''"),
        ("pitch_style", "TEXT DEFAULT ''"),
        ("signature", "TEXT DEFAULT ''"),
        ("outbound_delay_min", "INTEGER DEFAULT 180"),
        ("outbound_delay_max", "INTEGER DEFAULT 720"),
        ("reply_delay_seconds", "INTEGER DEFAULT 900"),
        ("smtp_host", "VARCHAR(200) DEFAULT ''"),
        ("smtp_port", "INTEGER DEFAULT 587"),
        ("smtp_user", "VARCHAR(320) DEFAULT ''"),
        ("smtp_password", "VARCHAR(300) DEFAULT ''"),
        ("smtp_from", "VARCHAR(320) DEFAULT ''"),
        ("imap_host", "VARCHAR(200) DEFAULT ''"),
        ("imap_port", "INTEGER DEFAULT 993"),
        ("imap_user", "VARCHAR(320) DEFAULT ''"),
        ("imap_password", "VARCHAR(300) DEFAULT ''"),
    ],
    "leads": [
        ("country", "VARCHAR(100) DEFAULT ''"),
        ("pain_points", "TEXT DEFAULT ''"),
        ("email_verified", "BOOLEAN DEFAULT 0"),
        ("batch_id", "INTEGER"),
        ("ai_paused", "BOOLEAN DEFAULT 0"),
        ("upload_tag", "VARCHAR(200) DEFAULT ''"),
        ("unsubscribed", "BOOLEAN DEFAULT 0"),
        ("unsub_token", "VARCHAR(64) DEFAULT ''"),
    ],
    "campaigns": [
        ("what_to_sell", "TEXT DEFAULT ''"),
        ("what_to_avoid", "TEXT DEFAULT ''"),
        ("target_focus", "TEXT DEFAULT ''"),
        ("target_country", "VARCHAR(100) DEFAULT ''"),
        ("email_length", "VARCHAR(20) DEFAULT 'concise'"),
        ("strategy", "VARCHAR(20) DEFAULT 'B2B'"),
        ("template_mode", "VARCHAR(20) DEFAULT 'template'"),
        ("batch_size", "INTEGER DEFAULT 20"),
        ("industry", "VARCHAR(120) DEFAULT ''"),
        ("email_length", "VARCHAR(20) DEFAULT 'concise'"),
        ("pain_focus", "TEXT DEFAULT ''"),
        ("sell_points", "TEXT DEFAULT ''"),
        ("avoid_points", "TEXT DEFAULT ''"),
    ],
    "email_messages": [("html_used", "BOOLEAN DEFAULT 0")],
    "users": [("is_superadmin", "BOOLEAN DEFAULT 0")],
    "templates": [("agent_id", "INTEGER")],
    "knowledge_docs": [("agent_id", "INTEGER")],
}


def run_migrations():
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in ADDITIVE.items():
            if table not in insp.get_table_names():
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))