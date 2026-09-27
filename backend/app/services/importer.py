"""The Excel/CSV import engine — runs in the background, not in the request.

Design rules, all learned from sheets that broke the old synchronous version:

1. NEVER one query per row. The old code did a SELECT + an SMTP/MX lookup + an
   INSERT + a flush for every single row: 80k rows meant ~320k round trips and
   a request that ran for an hour. Here the file is read once, de-duplicated in
   a set, and inserted in chunks of CHUNK with one bulk INSERT per chunk.

2. NEVER one DNS lookup per row either. MX is a property of the DOMAIN, so we
   resolve each unique domain once (a 80k-row sheet usually has a few thousand
   domains, often far fewer) and cache the answer in ResearchCache for good.
   That is the difference between 80k lookups and ~1k.

3. Progress is written every chunk, not every row, and always with a plain
   UPDATE. The user sees the bar move; the DB sees ~160 statements, not 80k.

4. Commit per chunk. A crash at row 60 000 keeps the first 60 000, and the
   de-dupe pass skips them on re-upload instead of exploding on the unique
   index.

5. Enrichment is per-DOMAIN: dnscheck/blocklist only need the domain, so
   junk-filters run once per domain and are cached with the MX verdict.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from ..database import SessionLocal
from .. import models
from . import excel_import, jobs, mailer, spam_filter
from .enroller import enqueue_fifo

log = logging.getLogger("chatversio.import")

CHUNK = 1000                # rows per bulk INSERT / progress tick
IN_CLAUSE = 500             # values per `IN (...)` when checking existing emails


def _chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _parse_job(job_id: int):
    db = SessionLocal()
    try:
        job = db.get(models.ImportJob, job_id)
        raw = bytes.fromhex(job.payload or "") if job and job.payload else b""
        fname, source = (job.filename, job.source) if job else ("", "excel")
        return raw, fname, source
    finally:
        db.close()


_PROBE_WORKERS = 12       # DNS lookups in flight; MX resolution is IO-wait bound


def _probe(dom: str) -> tuple[str, dict]:
    """One domain verdict: junk-filter first (free, no network), then MX."""
    bad = spam_filter.block_reason_for_recipient(f"probe@{dom}") or ""
    if bad:
        return dom, {"mx_ok": False, "blocked": bad}
    ok, _reason = mailer.verify_recipient(f"probe@{dom}", smtp=False)
    return dom, {"mx_ok": bool(ok), "blocked": ""}


def _domain_verdicts(domains: set[str]) -> dict:
    """One MX + junk check per unique domain, memoised in ResearchCache.

    The cache key is domain-scoped so a later 'Verify mailboxes' run reuses it
    too. Junk verdicts (disposable / role-account / notification sender
    domains) also short-circuit here, which is why a 80k-row junk sheet costs
    almost nothing.

    Both halves of this used to be serial: the cache READ was one query per
    domain (5 000 queries for a 5 000-domain sheet) and the cache WRITE was one
    COMMIT per domain. Now the reads are chunked IN queries, the lookups run on
    a small pool, and the writes are one commit per 500 domains."""
    verdicts: dict = {}
    if not domains:
        return verdicts
    doms = sorted(domains)
    db = SessionLocal()
    try:
        todo: list[str] = []
        for i in range(0, len(doms), IN_CLAUSE):
            keys = [f"mx:{d}" for d in doms[i:i + IN_CLAUSE]]
            cached = {h.cache_key[len("mx:"):]: h.research for h in
                      db.query(models.ResearchCache)
                      .filter(models.ResearchCache.cache_key.in_(keys)).all()}
            for d in doms[i:i + IN_CLAUSE]:
                raw = cached.get(d)
                if raw:
                    try:
                        verdicts[d] = json.loads(raw)
                        continue
                    except Exception:
                        pass
                todo.append(d)

        if todo:
            with ThreadPoolExecutor(max_workers=_PROBE_WORKERS) as pool:
                for dom, verdict in pool.map(_probe, todo):
                    verdicts[dom] = verdict
            for i in range(0, len(todo), 500):
                for dom in todo[i:i + 500]:
                    try:
                        db.merge(models.ResearchCache(
                            cache_key=f"mx:{dom}",
                            research=json.dumps(verdicts.get(dom) or {}),
                            pain_points="",
                        ))
                    except Exception:
                        db.rollback()      # cache is an optimisation, never fatal
                try:
                    db.commit()
                except Exception:
                    db.rollback()
    finally:
        db.close()
    return verdicts


def _existing_emails(db, emails: list[str], source: str) -> set[str]:
    """Which of these emails already exist in the queue being imported into.
    Chunked so a 2000-value IN clause never blows Postgres' parameter limit."""
    found: set[str] = set()
    for part in _chunked(emails, IN_CLAUSE):
        rows = (db.query(models.Lead.email)
                .filter(models.Lead.email.in_(part),
                        models.Lead.source == source).all())
        found.update(r[0] for r in rows)
    return found


def run_import(job_id: int) -> None:
    raw, filename, source = _parse_job(job_id)
    if not raw:
        jobs.update_job(job_id, status="error", phase="Upload payload lost — re-upload the file",
                        error="payload missing")
        return

    db = SessionLocal()
    try:
        job = db.get(models.ImportJob, job_id)
        campaign_id, agent_id = job.campaign_id, job.agent_id
        # Batch size is a Settings-page value, not a per-campaign one. The job
        # only records whatever was true at upload time; if it is missing or
        # stale we re-read the live setting.
        from .enroller import resolve_batch_size
        batch_size = resolve_batch_size(db, job.batch_size)
        do_enqueue = bool(job.auto_enroll and campaign_id and agent_id)
        campaign = db.get(models.Campaign, campaign_id) if campaign_id else None
        agent = db.get(models.Agent, agent_id) if agent_id else None
        if campaign_id and (not campaign or not agent):
            do_enqueue = False
        if source == "pitch":
            campaign = agent = None
            do_enqueue = False
        existing_batches = (db.query(models.Batch)
                            .filter(models.Batch.campaign_id == campaign.id).count()
                            ) if campaign else 0

        # ── 1. parse ────────────────────────────────────────────────────────
        jobs.update_job(job_id, status="running", phase="Reading the file…", pct=2)
        rows = excel_import.parse_leads(filename, raw)
        total = len(rows)
        jobs.update_job(job_id, total=total,
                        phase=f"Read {total:,} rows — checking addresses…",
                        pct=5 if total else 100)

        # ── 2. de-duplicate inside the file itself (no DB yet) ─────────────
        seen: set[str] = set()
        candidates, dupes_in_file = [], 0
        for row in rows:
            email = (row.get("email") or "").strip().lower()
            if not email:
                continue
            if email in seen:
                dupes_in_file += 1
                continue
            seen.add(email)
            row["email"] = email
            candidates.append(row)
        del rows

        # ── 3. one MX/junk verdict per unique domain, cached ───────────────
        domains = {r["email"].rsplit("@", 1)[1] for r in candidates if "@" in r["email"]}
        jobs.update_job(job_id, phase=f"Verifying {len(domains):,} domains…", pct=12)
        verdicts = _domain_verdicts(domains)

        # ── 4. de-duplicate against the DB (chunked IN) ───────────────────
        jobs.update_job(job_id, phase="Checking for duplicates…", pct=18)
        have = _existing_emails(db, [r["email"] for r in candidates], source)
        cross_db = set()
        if candidates:
            for part in _chunked([r["email"] for r in candidates], IN_CLAUSE):
                rows2 = (db.query(models.Lead.email, models.Lead.source)
                         .filter(models.Lead.email.in_(part)).all())
                cross_db.update((e, s) for (e, s) in rows2 if s != source)

        created = skipped = cross = blocked = unverified = 0
        fresh_ids: list[int] = []
        batch_seq = existing_batches
        bundle: list[models.Lead] = []
        made_batches: list[dict] = []
        now = datetime.utcnow()

        for start in range(0, len(candidates), CHUNK):
            part = candidates[start:start + CHUNK]
            payload, seen_now = [], set()
            for row in part:
                email = row["email"]
                if email in have:
                    skipped += 1                       # same queue → real duplicate
                    continue
                # Worthless address (info@/support@/noreply@/disposable) — never
                # stored, never contacted. Pure string check, no I/O.
                if spam_filter.block_reason_for_recipient(email):
                    blocked += 1
                    continue
                dom = email.rsplit("@", 1)[1]
                if (email, source) in cross_db:
                    cross += 1
                if email in seen_now:                  # belt & braces inside chunk
                    skipped += 1
                    continue
                seen_now.add(email)
                ok = bool((verdicts.get(dom) or {}).get("mx_ok"))
                if not ok:
                    unverified += 1
                payload.append(models.Lead(
                    name=(row.get("name") or "")[:200],
                    email=email,
                    company=(row.get("company") or "")[:300],
                    title=(row.get("title") or "")[:200],
                    phone=(row.get("phone") or "")[:60],
                    website=(row.get("website") or "")[:500],
                    country=(row.get("country") or "")[:100],
                    source=source,
                    email_verified=ok,
                    upload_tag=job.upload_tag,
                    # Assignment sticks even when auto-enroll is off (campaign
                    # paused / plain import): the Leads page filters by the
                    # selected agent, so an unstamped lead would be invisible
                    # exactly where the user just uploaded it from. Campaign
                    # stays unstamped — "enrolled" counts must stay truthful.
                    agent_id=(agent.id if agent else None),
                    created_at=now,
                ))

            if payload:
                db.add_all(payload)
                db.flush()                              # assigns .id
                created += len(payload)
                fresh_ids.extend(l.id for l in payload)
                if not do_enqueue:
                    bundle.extend(payload)
                    while len(bundle) >= batch_size:
                        batch_seq += 1
                        made_batches.append(
                            _make_batch(db, campaign, batch_seq, bundle[:batch_size]))
                        bundle = bundle[batch_size:]
            db.commit()

            done = min(start + CHUNK, len(candidates))
            pct = 20 + int(60 * done / max(1, len(candidates)))
            jobs.update_job(
                job_id, processed=done, created_count=created,
                skipped_count=skipped, cross_dup_count=cross,
                blocked_count=blocked, unverified_count=unverified,
                pct=pct, phase=f"Importing leads {done:,} / {len(candidates):,}…")

            # Honour a cancel between chunks: everything up to here is already
            # committed, so stopping here is clean and re-uploadable.
            if jobs.is_cancelled(job_id):
                jobs.update_job(
                    job_id, status="cancelled", pct=pct,
                    phase=(f"Cancelled after {done:,} row(s) — "
                           f"{created:,} lead(s) were already imported"))
                return

        if bundle:
            batch_seq += 1
            made_batches.append(_make_batch(db, campaign, batch_seq, bundle))
        db.commit()

        # ── 5. enroll + queue (background, never blocks the response) ─────
        # Batches cut above count too: a plain upload (no campaign to enroll
        # into) still made them, and the progress panel used to report
        # "0 batches" for a sheet that had been split into 50 + 10.
        batches = [{"number": m["number"], "size": m["size"], "id": m["id"]}
                   for m in made_batches]
        queued = 0
        if do_enqueue and fresh_ids:
            jobs.update_job(job_id, phase="Enrolling and queueing…", pct=85)
            leads = _by_id(db, fresh_ids)
            info = enqueue_fifo(db, campaign, agent, leads,
                                batch_size=batch_size,
                                existing_batches=existing_batches,
                                source_filename=filename)
            db.commit()
            queued = info["queued"]
            batches = [{"number": n, "size": sz, "id": bid}
                       for n, sz, bid in zip(info["batch_numbers"],
                                              info["batch_sizes"], info["batches"])]
        elif do_enqueue and created and not batches:
            # enqueue_fifo had nothing to hand out (every lead already had a
            # batch) — still give the page something truthful to show.
            batches = [{"number": existing_batches + 1,
                        "size": created, "id": 0}]

        receipt = {
            "created": created, "skipped_duplicates": skipped + dupes_in_file,
            "cross_duplicates": cross, "blocked_addresses": blocked,
            "unverified": unverified, "parsed": total,
            "unique_in_file": len(candidates), "source": source,
            "batch_size": batch_size, "batches": batches,
            "batch_count": len(batches), "auto_enrolled": queued,
            "campaign_id": campaign.id if do_enqueue else None,
            "agent_id": agent.id if do_enqueue else None,
            "upload_tag": job.upload_tag,
        }
        jobs.update_job(
            job_id, status="done", pct=100, processed=len(candidates),
            created_count=created, skipped_count=skipped + dupes_in_file,
            cross_dup_count=cross, blocked_count=blocked,
            unverified_count=unverified,
            # Drop the uploaded bytes: the file is up to tens of MB stored as
            # hex, and every finished receipt would otherwise pin that forever.
            payload="",
            phase=(f"Done — {created:,} lead(s) imported"
                   + (f", {queued:,} queued for sending" if queued else "")),
            result_json=json.dumps(receipt))
    except Exception as e:
        log.exception("import job %s crashed", job_id)
        db.rollback()
        jobs.update_job(job_id, status="error", pct=100, payload="",
                        phase=f"Import failed: {e}"[:300], error=str(e)[:2000])
    finally:
        db.close()


def _by_id(db, ids: list[int]) -> list[models.Lead]:
    out = []
    for part in _chunked(ids, IN_CLAUSE):
        out.extend(db.query(models.Lead)
                   .filter(models.Lead.id.in_(part))
                   .order_by(models.Lead.id).all())
    return out


def _make_batch(db, campaign, number: int, leads: list,
                source_filename: str = "") -> dict:
    tags = {(l.upload_tag or "")[:300] for l in leads}
    tags.discard("")
    fname = next(iter(tags)) if len(tags) == 1 else (source_filename or "")[:300]
    batch = models.Batch(campaign_id=campaign.id if campaign else None,
                         number=number, total=len(leads),
                         status=models.BatchStatus.pending,
                         source_filename=fname)
    db.add(batch)
    db.flush()
    for lead in leads:
        lead.batch_id = batch.id
    return {"number": number, "size": len(leads), "id": batch.id,
            "source_filename": fname}


def run_verify(job_id: int, ids: list[int] | None = None) -> None:
    """MX-verify unverified leads, one domain at a time, in the background.

    The old version did up to 500 blocking DNS lookups inside the request,
    which reliably timed out and came back as a 500. Two more things matter at
    volume: MX is cached per DOMAIN (so 20k leads at 300 companies is ~300
    lookups, not 20 000), and the write-back is one UPDATE per chunk instead of
    per row."""
    db = SessionLocal()
    try:
        base = (db.query(models.Lead)
                .filter(models.Lead.status != models.LeadStatus.garbage,
                        models.Lead.email_verified.isnot(True)))
        if ids:
            base = base.filter(models.Lead.id.in_(ids))
        total = base.with_entities(models.Lead.id).count()

        jobs.update_job(job_id, status="running", total=total,
                        phase=f"Verifying {total:,} mailboxes…", pct=1)

        pending_ids = [i for (i,) in base.with_entities(models.Lead.id)
                       .order_by(models.Lead.id).limit(50000).all()]
        # One row per lead, but only id+email: the ORM must not drag 50k full
        # Lead objects (with their Text research fields) into memory.
        rows = (db.query(models.Lead.id, models.Lead.email)
                .filter(models.Lead.id.in_(pending_ids)).all()) if pending_ids else []
        verdicts = _domain_verdicts({e.rsplit("@", 1)[1]
                                     for _i, e in rows if "@" in e})
        confirmed = still_bad = done = 0
        for i in range(0, len(rows), CHUNK):
            part = rows[i:i + CHUNK]
            ok_ids = [lid for lid, email in part
                      if (verdicts.get(email.rsplit("@", 1)[-1]) or {}).get("mx_ok")]
            bad_ids = [lid for lid, _e in part if lid not in set(ok_ids)]
            if ok_ids:
                db.query(models.Lead).filter(models.Lead.id.in_(ok_ids))\
                    .update({"email_verified": True}, synchronize_session=False)
                confirmed += len(ok_ids)
            if bad_ids:
                db.query(models.Lead).filter(models.Lead.id.in_(bad_ids))\
                    .update({"email_verified": False}, synchronize_session=False)
                still_bad += len(bad_ids)
            db.commit()
            done += len(part)
            jobs.update_job(
                job_id, processed=done, created_count=confirmed,
                skipped_count=still_bad,
                pct=2 + int(96 * done / max(1, len(rows))),
                phase=f"Verifying mailboxes {done:,} / {len(rows):,}…")
            if jobs.is_cancelled(job_id):
                jobs.update_job(
                    job_id, status="cancelled", pct=2 + int(96 * done / max(1, len(rows))),
                    phase=f"Cancelled after {done:,} mailbox(es) checked")
                return

        receipt = {"checked": done, "confirmed": confirmed,
                   "still_unverified": still_bad, "domains": len(verdicts)}
        jobs.update_job(job_id, status="done", pct=100, processed=done,
                        created_count=confirmed, skipped_count=still_bad,
                        payload="",
                        phase=(f"Checked {done:,} — {confirmed:,} reachable, "
                               f"{still_bad:,} unreachable"),
                        result_json=json.dumps(receipt))
    except Exception as e:
        log.exception("verify job %s crashed", job_id)
        db.rollback()
        jobs.update_job(job_id, status="error", pct=100, payload="",
                        phase=f"Verify failed: {e}"[:300], error=str(e)[:2000])
    finally:
        db.close()


def unverified_to_garbage() -> int:
    """Set-based so 40k unverified leads is one statement, not 40k ORM
    updates. `UPDATE … WHERE` also takes a row lock for the duration instead
    of pinning every instance in the session."""
    db = SessionLocal()
    try:
        n = (db.query(models.Lead)
             .filter(models.Lead.status != models.LeadStatus.garbage,
                     models.Lead.email_verified.is_(False))
             .update({"status": models.LeadStatus.garbage},
                     synchronize_session=False))
        db.commit()
        return n
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
