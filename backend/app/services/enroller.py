"""FIFO enqueue — the single place that turns a set of leads into an outbound
queue, in the order they were picked.

Chunks the leads into internal `Batch` rows (so Mail Records can answer "which
send went to which batch"), stamps each lead with its batch/campaign/agent, and
schedules the first email of each batch with a countdown. One email per `step`
(the agent's average outbound delay), strictly in selection order, and the next
batch's window starts after the current one — the queue ramps up safely instead
of dumping 50 emails on a mailbox at once.

SCALE — this used to fire one Celery task per lead. On an 80k-lead import that
is 80 000 broker messages in a single request: the broker crawls, the worker
dies, and the user gets a timeout. Now we fire ONE task per BATCH, and that
task walks its own leads internally with the same spacing, so 80k leads become
~1 600 broker messages spread over days, and an import finishes queueing in
seconds.

The per-agent daily cap and the same-day cross-agent dedupe are still enforced
per email inside start_campaign_lead itself, so a big enqueue can never
outrun them.

The campaign screen never shows any of this — it only reports a send count.
Batch numbers are a Mail Records concern.
"""
from datetime import datetime

from .. import models


def resolve_batch_size(db, requested: int | None = None) -> int:
    """How many leads go into one Batch.

    Deliberately NOT a campaign field. The operator sets it once on the
    Settings page ("email batch size") and every campaign, upload and manual
    launch uses it, so there is exactly one place that decides how big a batch
    is. An explicit `requested` (an upload form) wins, but it is still clamped
    to the min/max the Settings page allows."""
    from ..routers.app_settings import get_runtime_setting
    lo = 10
    hi = 2000
    try:
        lo = int(get_runtime_setting(db, "batch_size_min") or 10)
        hi = int(get_runtime_setting(db, "batch_size_max") or 2000)
    except (TypeError, ValueError):
        pass
    if lo > hi:
        lo, hi = hi, lo
    value = requested
    if not value:
        try:
            value = int(get_runtime_setting(db, "email_batch_size") or 50)
        except (TypeError, ValueError):
            value = 50
    return max(lo, min(hi, int(value)))


def enqueue_fifo(db, campaign, agent, leads, *, start_batch_number: int = 1,
                 batch_size: int | None = None, enroll: bool = True,
                 existing_batches: int = 0, source_filename: str = ""):
    """Tag + schedule `leads` for `campaign`/`agent`. Returns
    {batches: [ids], batch_numbers: [..], batch_sizes: [..], queued: n,
     batch_size: size}."""
    from ..tasks import dispatch_batch   # lazy: tasks imports services

    leads = list(leads)
    if not leads:
        return {"batches": [], "batch_numbers": [], "batch_sizes": [],
                "queued": 0, "batch_size": batch_size or 0}

    size = resolve_batch_size(db, batch_size)
    # Spacing comes from the agent when it has its own, otherwise from the
    # Settings page — never from a number hardcoded here.
    from ..tasks import _outbound_delay_bounds
    lo, hi = _outbound_delay_bounds(agent, db) if agent else (180, 720)
    step = max(60, (lo + hi) // 2)      # one email every `step` seconds, in order

    # The Excel a lead came from, so Mail Records can group batches by file.
    if not source_filename:
        tags = {getattr(l, "upload_tag", "") for l in leads}
        tags.discard("")
        source_filename = next(iter(tags), "") if len(tags) == 1 else ""

    # Never put a lead back in a sequence the agent already walked away from.
    # not_interested = they declined (silent, in Garbage, purged later);
    # needs_human = waiting on a person; escalated = parked out of Messages.
    # Re-enrolling any of these would restart an email sequence the user
    # explicitly asked to stop, so they are dropped and counted, not sent to.
    blocked = [l for l in leads if l.not_interested or l.needs_human
               or l.escalated or l.unsubscribed]
    # TARGETING RULES — the agent's own exclusions (excluded job titles,
    # excluded companies / company types) and its positive targeting
    # (target titles, target location). Checked here because every route into
    # the queue — the Leads page, "enroll all matching", a whole batch, an
    # Excel import, a campaign launch — comes through this function.
    from . import targeting as targeting_service
    from . import agent_settings
    from . import ownership as ownership_service
    excluded: dict[str, int] = {}
    held_owners: dict[str, int] = {}
    if agent is not None:
        # The campaign's selection box decides which targeting halves apply.
        parts = (agent_settings.enabled_keys(campaign)
                 if campaign is not None else None)
        own_days = ownership_service.ownership_days(db)
        keep = []
        for l in leads:
            # OWNERSHIP — a lead whose owner is still actively communicating
            # can never be silently re-stamped onto another agent here. A
            # released lead (owner paused / silent past the timeline) passes.
            if l.agent_id and l.agent_id != agent.id:
                is_held, why = ownership_service.held(db, l, days=own_days)
                if is_held:
                    held_owners[why] = held_owners.get(why, 0) + 1
                    continue
            reason = targeting_service.exclusion_reason(agent, l, parts=parts)
            if reason:
                key = reason.split(" (")[0]
                excluded[key] = excluded.get(key, 0) + 1
            else:
                keep.append(l)
        leads = keep

    if blocked or excluded or held_owners:
        blocked_ids = {l.id for l in blocked}
        leads = [l for l in leads if l.id not in blocked_ids]
        reasons = {
            "not_interested": sum(1 for l in blocked if l.not_interested),
            "needs_human": sum(1 for l in blocked if l.needs_human),
            "escalated": sum(1 for l in blocked if l.escalated and not l.needs_human),
            "unsubscribed": sum(1 for l in blocked if l.unsubscribed),
        }
        if held_owners:
            reasons["held_by_owner"] = sum(held_owners.values())
            reasons["owners"] = held_owners
        if excluded:
            reasons["excluded_targeting"] = sum(excluded.values())
            reasons["exclusions"] = excluded
        if not leads:
            return {"batches": [], "batch_numbers": [], "batch_sizes": [],
                    "queued": 0, "batch_size": size,
                    "skipped_count": len(blocked_ids) + sum(excluded.values())
                                     + sum(held_owners.values()),
                    "skipped_reasons": reasons}

    batches_made, batch_numbers, batch_sizes = [], [], []
    batch_offset = 0

    # Build chunks that never straddle a source file, so every batch belongs to
    # exactly one Excel. That is what makes "this batch, from this sheet" a
    # real thing in Mail Records instead of a mix nobody can explain later.
    # Order is preserved inside each file, then files in first-seen order.
    order: list[str] = []
    by_file: dict[str, list] = {}
    for lead in leads:
        fname = ((getattr(lead, "upload_tag", "") or "")[:300]
                 or source_filename[:300])
        if fname not in by_file:
            by_file[fname] = []
            order.append(fname)
        by_file[fname].append(lead)

    chunks: list[tuple[str, list]] = []
    for fname in order:
        group = by_file[fname]
        for i in range(0, len(group), size):
            chunks.append((fname, group[i:i + size]))

    for fname, chunk in chunks:
        number = existing_batches + len(batches_made) + 1
        batch = models.Batch(campaign_id=campaign.id if campaign else None,
                             number=number, total=len(chunk),
                             status=models.BatchStatus.pending,
                             source_filename=fname,
                             created_at=datetime.utcnow())
        db.add(batch)
        db.flush()
        for lead in chunk:
            if campaign is not None:
                lead.campaign_id = campaign.id
            if agent is not None:
                lead.agent_id = agent.id
            lead.batch_id = batch.id
            if enroll:
                lead.status = models.LeadStatus.enrolled
        # COMMIT BEFORE PUBLISH. The worker runs on its own connection, so a
        # task published before this commit can arrive at a row it cannot see
        # yet; dispatch_batch then answered "no-batch" and the whole batch was
        # stranded at `pending` forever with no retry. Make the row visible
        # first, then tell anyone about it.
        db.commit()
        # ONE task per batch. It re-reads the batch's leads in id order, so the
        # queue is fully reconstructible from the DB and survives a restart.
        dispatch_batch.apply_async(args=[batch.id], countdown=batch_offset)
        batches_made.append(batch.id)
        batch_numbers.append(number)
        batch_sizes.append(len(chunk))
        batch_offset += len(chunk) * step   # next batch after this window
    return {"batches": batches_made, "batch_numbers": batch_numbers,
            "batch_sizes": batch_sizes, "queued": len(leads), "batch_size": size,
            "step_seconds": step,
            "source_filenames": [f for f in order if f],
            "skipped_count": len(blocked) + sum(excluded.values())
                             + sum(held_owners.values()),
            "skipped_reasons": {
                "not_interested": sum(1 for l in blocked if l.not_interested),
                "needs_human": sum(1 for l in blocked if l.needs_human),
                "escalated": sum(1 for l in blocked if l.escalated and not l.needs_human),
                "unsubscribed": sum(1 for l in blocked if l.unsubscribed),
                **({"held_by_owner": sum(held_owners.values()),
                    "owners": held_owners} if held_owners else {}),
                **({"excluded_targeting": sum(excluded.values()),
                    "exclusions": excluded} if excluded else {}),
            } if (blocked or excluded or held_owners) else {}}
