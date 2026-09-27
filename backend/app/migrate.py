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
        ("sentiment_prompt", "TEXT DEFAULT ''"),
        ("country_prompt", "TEXT DEFAULT ''"),
        ("judgment_prompt", "TEXT DEFAULT ''"),
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
        # ── who to target, what to present, what never to say ───────────────
        ("persona", "VARCHAR(30) DEFAULT ''"),
        ("why_you", "TEXT DEFAULT ''"),
        ("target_titles", "TEXT DEFAULT ''"),
        ("target_location", "VARCHAR(200) DEFAULT ''"),
        ("excluded_titles", "TEXT DEFAULT ''"),
        ("excluded_companies", "TEXT DEFAULT ''"),
        ("solutions", "TEXT DEFAULT ''"),
        ("avoid_phrases", "TEXT DEFAULT ''"),
        ("extra_instructions", "TEXT DEFAULT ''"),
    ],
    "leads": [
        ("country", "VARCHAR(100) DEFAULT ''"),
        ("pain_points", "TEXT DEFAULT ''"),
        ("email_verified", "BOOLEAN DEFAULT false"),
        ("batch_id", "INTEGER"),
        ("ai_paused", "BOOLEAN DEFAULT false"),
        ("upload_tag", "VARCHAR(200) DEFAULT ''"),
        ("unsubscribed", "BOOLEAN DEFAULT false"),
        ("unsub_token", "VARCHAR(64) DEFAULT ''"),
        ("pitch_done", "BOOLEAN DEFAULT false"),
        ("escalated", "BOOLEAN DEFAULT false"),
        ("escalation_reason", "VARCHAR(300) DEFAULT ''"),
        # ── follow-up strategy + human-review flags ─────────────────────────
        # "A human has to answer this" — thread stays in Messages, agent stops.
        ("needs_human", "BOOLEAN DEFAULT false"),
        ("needs_human_reason", "VARCHAR(300) DEFAULT ''"),
        # "Not interested" -> silent agent, Garbage inbox, 30-day purge.
        ("not_interested", "BOOLEAN DEFAULT false"),
        ("not_interested_at", "TIMESTAMP"),
        ("not_interested_note", "VARCHAR(300) DEFAULT ''"),
        ("garbage_at", "TIMESTAMP"),
        ("last_outbound_subject", "VARCHAR(300) DEFAULT ''"),
    ],
    "campaigns": [
        ("what_to_sell", "TEXT DEFAULT ''"),
        ("what_to_avoid", "TEXT DEFAULT ''"),
        ("target_focus", "TEXT DEFAULT ''"),
        ("target_country", "VARCHAR(100) DEFAULT ''"),
        ("email_length", "VARCHAR(20) DEFAULT 'concise'"),
        ("strategy", "VARCHAR(20) DEFAULT 'B2B'"),
        ("template_mode", "VARCHAR(20) DEFAULT 'template'"),
        # DEPRECATED/UNUSED: batch size is a Settings-page value now. Kept only
        # so pre-existing campaign rows keep their column.
        ("batch_size", "INTEGER DEFAULT 50"),
        ("industry", "VARCHAR(120) DEFAULT ''"),
        ("pain_focus", "TEXT DEFAULT ''"),
        ("sell_points", "TEXT DEFAULT ''"),
        ("avoid_points", "TEXT DEFAULT ''"),
        ("strategy_notes", "TEXT DEFAULT ''"),
        ("followup_1_hours", "INTEGER DEFAULT 24"),
        ("followup_2_hours", "INTEGER DEFAULT 48"),
        ("followup_3_hours", "INTEGER DEFAULT 72"),
        ("followup_max_days", "INTEGER DEFAULT 30"),
        # ── follow-up strategy + human-review flags ─────────────────────────
        # Days-wise plan ("3,7,14") + count-wise cap. Empty plan = the legacy
        # followup_N_hours stage timing, so nothing changes for existing rows.
        ("followup_plan", "VARCHAR(200) DEFAULT ''"),
        ("followup_count", "INTEGER DEFAULT 3"),
        ("followup_memory", "BOOLEAN DEFAULT true"),
        # "not interested" -> Garbage for 30 days, agent goes silent.
        ("not_interested_action", "VARCHAR(20) DEFAULT 'garbage'"),
        ("not_interested_retention_days", "INTEGER DEFAULT 30"),
        # Never let the AI answer pricing / contract / legal on its own.
        ("pricing_policy", "VARCHAR(20) DEFAULT 'escalate'"),
        ("first_email_length", "VARCHAR(20) DEFAULT ''"),
        ("demo_offer", "BOOLEAN DEFAULT true"),
        ("subject_max_words", "INTEGER DEFAULT 3"),
        # ── what are you offering + delivery model ───────────────────────────
        ("offering", "TEXT DEFAULT ''"),
        ("delivery_model", "TEXT DEFAULT ''"),
        ("ideal_customer", "TEXT DEFAULT ''"),
        ("platform_rules", "TEXT DEFAULT ''"),
        ("no_pricing", "BOOLEAN DEFAULT true"),
        ("cta_enabled", "BOOLEAN DEFAULT true"),
        ("booking_link", "VARCHAR(500) DEFAULT ''"),
        # ── follow-up schedule: weekday window + time of day (UTC) ───────────
        ("followup_days", "VARCHAR(60) DEFAULT ''"),
        ("followup_time", "VARCHAR(5) DEFAULT ''"),
        # ── which parts of the agent this campaign may drive ("" = all) ──────
        ("agent_parts", "VARCHAR(500) DEFAULT ''"),
    ],
    "email_messages": [
        ("html_used", "BOOLEAN DEFAULT false"),
        ("is_escalation", "BOOLEAN DEFAULT false"),
        ("escalation_reason", "VARCHAR(300) DEFAULT ''"),
    ],
    "users": [("is_superadmin", "BOOLEAN DEFAULT false")],
    "templates": [("agent_id", "INTEGER")],
    "knowledge_docs": [("agent_id", "INTEGER")],
    "import_jobs": [
        ("kind", "VARCHAR(40) DEFAULT 'upload'"),
        ("filename", "VARCHAR(300) DEFAULT ''"),
        ("source", "VARCHAR(40) DEFAULT 'excel'"),
        ("status", "VARCHAR(20) DEFAULT 'queued'"),
        ("phase", "VARCHAR(300) DEFAULT ''"),
        ("pct", "INTEGER DEFAULT 0"),
        ("total", "INTEGER DEFAULT 0"),
        ("processed", "INTEGER DEFAULT 0"),
        ("created_count", "INTEGER DEFAULT 0"),
        ("skipped_count", "INTEGER DEFAULT 0"),
        ("cross_dup_count", "INTEGER DEFAULT 0"),
        ("blocked_count", "INTEGER DEFAULT 0"),
        ("unverified_count", "INTEGER DEFAULT 0"),
        ("batch_size", "INTEGER DEFAULT 50"),
        ("campaign_id", "INTEGER"),
        ("agent_id", "INTEGER"),
        ("auto_enroll", "BOOLEAN DEFAULT false"),
        ("upload_tag", "VARCHAR(200) DEFAULT ''"),
        ("error", "TEXT DEFAULT ''"),
        ("payload", "TEXT DEFAULT ''"),
        ("result_json", "TEXT DEFAULT ''"),
        ("updated_at", "TIMESTAMP"),
    ],
    "batches": [
        # Which Excel a batch came from, so Mail Records can list "this sheet ->
        # its batches" and a batch can be enrolled on its own.
        ("source_filename", "VARCHAR(300) DEFAULT ''"),
    ],
}


def _assert_no_duplicate_tables(additive: dict) -> None:
    """Fail loudly if one table is listed twice in ADDITIVE.

    Python keeps only the LAST value for a repeated dict key, so a second
    "leads": [...] block silently discards the first one — the columns in it
    then never get added to an older database and the app dies later with
    'column does not exist' far away from the real mistake. It happened once
    (the escalation columns vanished this way), so it is checked every boot."""
    import re
    from pathlib import Path
    src = Path(__file__).read_text(encoding="utf-8")
    start = src.index("ADDITIVE = {")
    body = src[start:src.index("\ndef ", start)]
    seen, dupes = set(), []
    for m in re.finditer(r'^\s{4}"([a-z_]+)":\s*\[', body, re.M):
        t = m.group(1)
        if t in seen:
            dupes.append(t)
        seen.add(t)
    if dupes:
        raise RuntimeError(
            f"migrate.ADDITIVE lists {sorted(set(dupes))} more than once — merge "
            "the blocks, the earlier one is being dropped silently")


def _pitch_email_uniqueness(conn):
    """Pitch leads and Excel (outreach) leads are separate queues, but the
    old schema enforced a GLOBAL unique(email) — so the same email could
    never live in both, silently cancelling one side out. Replace it with
    per-source uniqueness UNIQUE(email, source): one Excel row + one Pitch
    row may share an email. Safe: global uniqueness before means no
    cross-source duplicates exist to clean up. Never touches data."""
    insp = inspect(conn)
    try:
        uniqs = {c["name"] for c in insp.get_unique_constraints("leads")}
    except Exception:
        return
    if "uq_lead_email" in uniqs:
        conn.execute(text("ALTER TABLE leads DROP CONSTRAINT uq_lead_email"))
        insp = inspect(conn)
        uniqs = {c["name"] for c in insp.get_unique_constraints("leads")}
    if "uq_lead_email_source" not in uniqs:
        conn.execute(text(
            "ALTER TABLE leads ADD CONSTRAINT uq_lead_email_source "
            "UNIQUE (email, source)"
        ))


def _retention_defaults(conn):
    """Old campaigns were created with followup_max_days = 7, which threw leads
    into Garbage a week after import. The rule now is a flat 30 days across the
    board, so bump exactly the old default and leave any value a human actually
    chose alone. Idempotent - once 7s are gone this updates nothing."""
    insp = inspect(conn)
    if "campaigns" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("campaigns")}
    if "followup_max_days" not in cols:
        return
    conn.execute(text("UPDATE campaigns SET followup_max_days = 30 "
                      "WHERE followup_max_days = 7"))


# Indexes added after the fact. An existing table gets the column from ADDITIVE
# above, but ALTER TABLE ADD COLUMN never creates the index, so we create them
# here — the Escalation page filters on is_escalation across 50k+ rows and a
# sequential scan per page load is not acceptable.
ADDITIVE_INDEXES = {
    "email_messages": [
        ("ix_email_messages_is_escalation", ["is_escalation"]),
        # Mail Records / Inbox / per-lead thread all filter on the lead and
        # then order by time. Without this composite, listing a thread on an
        # 80k-lead table sorts every message of that lead in memory.
        ("ix_em_lead_created", ["lead_id", "created_at"]),
        # "did we already email this person?" runs on every enroll + every send
        # attempt. This composite is the single hottest query in the product.
        ("ix_em_lead_dir", ["lead_id", "direction"]),
        # Outbound cap / follow-up sweeps: agent + direction + time window.
        ("ix_em_agent_dir_created", ["agent_id", "direction", "created_at"]),
        ("ix_em_dir_created", ["direction", "created_at"]),
    ],
    "leads": [
        ("ix_leads_escalated", ["escalated"]),
        # The Leads list is always "source + status, ordered by priority then
        # date". This composite serves the filter AND the sort.
        ("ix_leads_src_status_prio", ["source", "status", "priority", "created_at"]),
        ("ix_leads_status", ["status"]),
        ("ix_leads_created", ["created_at"]),
        ("ix_leads_agent", ["agent_id"]),
        ("ix_leads_campaign", ["campaign_id"]),
        ("ix_leads_batch", ["batch_id"]),
        # Import de-dupe: one lookup per chunk of incoming emails, scoped to
        # the queue being imported into.
        ("ix_leads_source_email", ["source", "email"]),
        # "enroll all matching" resolves the page filter to ids server-side, so
        # the search box has to be indexable too (unverified-only / unassigned).
        ("ix_leads_status_verified", ["status", "email_verified"]),
        ("ix_leads_status_agent", ["status", "agent_id"]),
        # The Pitch Decker is literally "leads WHERE source=pitch AND
        # pitch_done=false, newest first" — without this the queue list seq-scans
        # 80k rows on every page load.
        ("ix_leads_pitch_queue", ["source", "pitch_done", "created_at"]),
        # The Garbage inbox + its 30-day purge: "leads in garbage since X".
        ("ix_leads_garbage_at", ["status", "garbage_at"]),
        ("ix_leads_not_interested", ["not_interested", "status"]),
        ("ix_leads_needs_human", ["needs_human", "status"]),
    ],
    "import_jobs": [
        ("ix_import_jobs_status", ["status"]),
        ("ix_import_jobs_kind_id", ["kind", "id"]),
    ],
    "batches": [
        ("ix_batches_campaign", ["campaign_id", "number"]),
        # Mail Records groups batches by source file.
        ("ix_batches_source", ["source_filename"]),
    ],
}


def run_migrations():
    _assert_no_duplicate_tables(ADDITIVE)
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in ADDITIVE.items():
            if table not in insp.get_table_names():
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        _pitch_email_uniqueness(conn)
        _retention_defaults(conn)
        for table, idxes in ADDITIVE_INDEXES.items():
            if table not in insp.get_table_names():
                continue
            have = set()
            try:
                have = {ix["name"] for ix in insp.get_indexes(table)}
            except Exception:
                pass
            for name, cols in idxes:
                if name in have:
                    continue
                col_list = ", ".join(cols)
                try:
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} "
                                      f"ON {table} ({col_list})"))
                except Exception:
                    pass