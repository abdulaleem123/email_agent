import React, { useEffect, useRef, useState, useCallback } from 'react'
import { api } from '../api.js'
import MiniOrb from '../MiniOrb.jsx'
import { Toast, useToast, useOpenAIKey } from '../App.jsx'
import Counter from '../Counter.jsx'
import ImportProgress, { useImportJob } from '../ImportProgress.jsx'
import { IconUsers, IconPlus, IconTrash, IconRefresh, IconSearch, IconRocket } from '../Icons.jsx'
 
/**
 * Leads — the queue of people your agents will reach out to.
 *
 * Built for 80 000+ leads: server-side paging everywhere, every bulk action
 * set-based on the server, and uploads/verification run as QUEUED background
 * jobs with a live progress bar instead of a request that hangs and then 500s.
 */
export default function Leads() {
  const { openaiReady } = useOpenAIKey()
  const aiDisabled = openaiReady === false
  const imp = useImportJob()
  const [data, setData] = useState({ items: [], total: 0, page: 1, per_page: 25 })
  const [stats, setStats] = useState(null)
  const [page, setPage] = useState(1)
  const perPage = 25
  const [status, setStatus] = useState('')
  const [unverifiedOnly, setUnverifiedOnly] = useState(false)
  const [unassignedOnly, setUnassignedOnly] = useState(false)
  // Threads the agent refused to answer (price / contract / legal / security)
  // and leads that said "not interested". Both are dead to the agent — this is
  // where you find out what it stopped on.
  const [humanOnly, setHumanOnly] = useState('')
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [campaigns, setCampaigns] = useState([])
  const [agents, setAgents] = useState([])
  const [sel, setSel] = useState(new Set())
  const [bulkAgent, setBulkAgent] = useState('')      // agent chosen for 'assign all selected'
  const [rowAgentSel, setRowAgentSel] = useState({})   // leadId -> chosen agent_id in the row dropdown
  const [campaignId, setCampaignId] = useState('')
  const [agentId, setAgentId] = useState('')
  const [busy, setBusy] = useState(false)
  const [verifying, setVerifying] = useState(false)
  const [showHow, setShowHow] = useState(false)
  // Which Excel / which batch this view is about. Both feed straight into
  // "Enroll all matching", so a sheet (or a single 20/30/40/50 batch of it) can
  // be launched on its own without re-selecting rows.
  const [sourceFiles, setSourceFiles] = useState([])
  const [sourceFile, setSourceFile] = useState('')
  const [batchFilter, setBatchFilter] = useState('')
  // Batch size is NOT chosen here. It lives on the Settings page (one knob for
  // the whole system); this page only shows what it currently is, read-only, so
  // it is never a mystery why an upload split the way it did.
  const [batchSize, setBatchSize] = useState(0)   // 0 = "use the Settings value"
  const [autoEnroll, setAutoEnroll] = useState(true)      // import = enroll + start sending right away
  const fileRef = useRef()
  const [toast, show] = useToast()
 
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 300)
    return () => clearTimeout(t)
  }, [q])
  useEffect(() => { setPage(1) }, [status, debouncedQ, unverifiedOnly, unassignedOnly, agentId, humanOnly, sourceFile, batchFilter])
 
  const load = useCallback(async () => {
    const params = new URLSearchParams({ page, per_page: perPage })
    if (status) params.set('status', status)
    if (debouncedQ) params.set('q', debouncedQ)
    if (unverifiedOnly) params.set('unverified_only', 'true')
    if (unassignedOnly) params.set('unassigned_only', 'true')
    if (humanOnly) params.set(humanOnly, 'true')
    if (agentId) params.set('agent_id', agentId)
    if (sourceFile) params.set('source_file', sourceFile)
    if (batchFilter) params.set('batch_id', batchFilter)
    try {
      const [d, s, cs, ag, st] = await Promise.all([
        api.leadsPaged(params.toString()),
        api.leadsStats(),
        api.campaigns(),
        api.agents(),
        api.getSettings().catch(() => null),
      ])
      setData(d); setStats(s); setCampaigns(cs); setAgents(ag)
      if (st) setBatchSize(+(st.email_batch_size || 0))
      if (cs.length && !campaignId) setCampaignId(String(cs[0].id))
    } catch (e) { show(e.message, true) }
  }, [page, status, debouncedQ, campaignId, agentId, unassignedOnly, unverifiedOnly, humanOnly, sourceFile, batchFilter, show])
 
  useEffect(() => { load() }, [load])

  // The Excel files that have batches, for the "one sheet at a time" filter.
  useEffect(() => {
    api.mailRecordBatches({ limit: 200 })
      .then(d => setSourceFiles(d?.source_files || []))
      .catch(() => {})
  }, [data.total, imp.job?.status])
 
  const upload = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    // Auto-enroll only makes sense with a real campaign + agent, otherwise the
    // leads are imported and queued as bundles for a manual launch later.
    const enroll = autoEnroll && !!campaignId && !!agentId
    if (autoEnroll && (!campaignId || !agentId))
      show('Pick a campaign AND an agent first — importing without both just stores the leads', true)
    setBusy(true)
    try {
      // The POST only queues the work: it returns 202 + job_id in milliseconds
      // and the progress bar below follows the job to the end.
      const r = await api.uploadLeads(file, agentId || undefined, campaignId || undefined, 'excel', null, enroll)
      if (r?.job_id) {
        imp.watch(r.job_id)
        show(`${file.name} queued — ${r.batch_size || batchSize}-lead bundles`)
      } else {
        show('Upload finished', true)
        load()
      }
    } catch (ex) { show(ex.message, true) } finally { setBusy(false); e.target.value = '' }
  }

  // A refresh (or another tab) must not lose a running import.
  useEffect(() => { imp.adoptRunning() }, [])
 
  const verifyMailboxes = async () => {
    setVerifying(true)
    try {
      // Queued too: MX lookups are DNS round trips, and doing 500 of them
      // inside the request is exactly what used to time out into a 500.
      const r = await api.verifyMailboxes()
      if (r?.job_id) { imp.watch(r.job_id); show('Mailbox verification queued') }
      else load()
    } catch (ex) { show(ex.message, true) } finally { setVerifying(false) }
  }
 
  const bulkGarbage = async () => {
    if (!sel.size) return
    setBusy(true)
    try { const r = await api.bulkGarbageLeads([...sel]); show(`Moved ${r.moved} lead(s) → Trash`); setSel(new Set()); load() }
    catch (ex) { show(ex.message, true) } finally { setBusy(false) }
  }
 
  // BULK ASSIGN: pick ONE agent, apply to every selected lead at once (assign +
  // enroll) — no more per-row 'Pick agent' one-by-one.
  //
  // enroll ALONE queues the sends (it cuts the batches and schedules them).
  // Calling api.launch afterwards used to queue the SAME leads a second time,
  // which is how a lead got two identical cold emails. One enqueue only.
  const enrollSelectedWith = async () => {
    if (!campaignId) { show('Pick a campaign first', true); return }
    if (!bulkAgent) { show('Choose an agent to assign', true); return }
    const ids = [...sel].filter(id => launchable.some(l => l.id === id))
    if (!ids.length) { show('None of the selected leads are enrollable (new/enrolled only)', true); return }
    const who = agents.find(a => a.id === +bulkAgent)?.name || 'agent'
    setBusy(true)
    try {
      const r = await api.enroll(ids, +campaignId, +bulkAgent)
      const queued = r?.enrolled ?? ids.length
      show(`${queued} lead(s) assigned to ${who} & queued in ${r?.batches?.length || 0} batch(es)`)
      setSel(new Set()); load()
    } catch (ex) { show(ex.message, true) } finally { setBusy(false) }
  }
 
  const moveUnverifiedToGarbage = async () => {
    if (!confirm('Move ALL unverified leads to Trash? They are not deleted — you can review or restore them from Trash.')) return
    setBusy(true)
    try { const r = await api.unverifiedToGarbage(); show(`Moved ${r.moved} unverified lead(s) to Trash`); load() }
    catch (ex) { show(ex.message, true) } finally { setBusy(false) }
  }
 
  const deleteAll = async () => {
    if (!confirm('Delete ALL leads and their messages? This wipes the whole sheet.')) return
    setBusy(true)
    try { const r = await api.deleteAllLeads(); show(`Deleted ${r.deleted} leads`); load() }
    catch (ex) { show(ex.message, true) } finally { setBusy(false) }
  }
 
  const [purgeDays, setPurgeDays] = useState(null)   // null = modal closed, else the typed value
 
  const runPurge = async () => {
    const n = parseInt(purgeDays, 10)
    if (!Number.isFinite(n) || n < 1) { show('Enter a positive number', true); return }
    try { const r = await api.purgeCompletedLeads(n); show(`Purged ${r.deleted} leads`); load() }
    catch (ex) { show(ex.message, true) } finally { setPurgeDays(null) }
  }
 
  const launchable = data.items.filter(l => ['new', 'enrolled'].includes(l.status))
  const toggleAll = () => setSel(s => s.size === launchable.length ? new Set() : new Set(launchable.map(l => l.id)))
  const toggleOne = (id) => setSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
 
  const [blockedInfo, setBlockedInfo] = useState(null)
 
  const enrollOneWithAgent = async (lead, chosenAgentId) => {
    if (!chosenAgentId || !campaignId) { show('Pick a campaign in the toolbar above first', true); return }
    try {
      // ONE call. enroll already queues the first email — a second launch call
      // re-queued the same lead and the lead was emailed twice.
      const r = await api.enroll([lead.id], +campaignId, +chosenAgentId)
      if (r.blocked?.length) { setBlockedInfo(r.blocked); return }
      if (r.handed_over) {
        show(`${lead.name || lead.email} handed over — the sequence continues as follow-ups (no new cold email)`)
        load(); return
      }
      show(`${lead.name || lead.email} enrolled with ${agents.find(a => a.id === +chosenAgentId)?.name || 'agent'} — queued`)
      load()
    } catch (ex) { show(ex.message, true) }
  }
  
  const enrollAndLaunch = async () => {
    if (!sel.size || !campaignId) return
    setBusy(true)
    try {
      const ids = [...sel]
      // enroll = assign + cut batches + schedule the sends. Nothing else is
      // needed: a follow-up launch call would queue the leads a second time.
      const r = await api.enroll(ids, +campaignId, agentId ? +agentId : undefined)
      if (r.blocked?.length) {
        setBlockedInfo(r.blocked)
      }
      const blockedIds = new Set((r.blocked || []).map(b => b.lead_id))
      const overIds = new Set(r.handed_over_ids || [])
      const goIds = ids.filter(id => !blockedIds.has(id) && !overIds.has(id))
      if (goIds.length) {
        show(`Queued ${r.enrolled} email(s) in ${r.batches?.length || 0} batch(es) of ~${r.batch_size}`
             + (r.handed_over ? ` · ${r.handed_over} handed over (follow-ups continue)` : ''))
      } else if (r.handed_over) {
        show(`${r.handed_over} lead(s) handed over — sequence continues as follow-ups`)
      } else if (!r.blocked?.length) {
        show('Nothing to enroll', true)
      }
      setSel(new Set()); load()
    } catch (ex) { show(ex.message, true) } finally { setBusy(false) }
  }
 
  // SELECT-ALL-MATCHING: enroll every lead in the current filter (all pages),
  // without shipping thousands of IDs. Great for 20k–50k sheets and for
  // "assign all unassigned leads to <agent>".
  const enrollAllMatching = async () => {
    if (!campaignId) { show('Pick a campaign first', true); return }
    const who = agentId ? (agents.find(a => a.id === +agentId)?.name || 'agent') : null
    const target = who || (campaigns.find(c => c.id === +campaignId)?.name && 'the campaign\u2019s default agent')
    if (!agentId) { show('Pick an agent in the toolbar to enroll all matching', true); return }
    if (!confirm(`Enroll ALL ${data.total} matching lead(s) into this campaign with ${who}? They queue in batches automatically.`)) return
    setBusy(true)
    try {
      // The whole filter is resolved SERVER-side: "enroll all matching" must
      // cover every page, not the 25 rows currently rendered. Sending
      // 80 000 ids from the browser is what used to blow up the request.
      const r = await api.enrollByFilter({
        status: status || undefined,
        // when filtering to unassigned leads, don't also restrict by a current
        // agent (they'd contradict) — we're assigning them FOR THE FIRST TIME
        agent_id: (!unassignedOnly && agentId) ? +agentId : undefined,
        unverified_only: unverifiedOnly,
        unassigned_only: unassignedOnly,
        needs_human_only: humanOnly === 'needs_human_only',
        not_interested_only: humanOnly === 'not_interested_only',
        source_file: sourceFile || undefined,
        batch_id: batchFilter || undefined,
        q: debouncedQ || '',
      }, +campaignId, +agentId)
      show(`Enrolled ${r.enrolled} · queued in ${r.batches?.length || 0} batch(es) of ~${r.batch_size}` +
           (r.blocked_count ? ` · ${r.blocked_count} skipped (24h lock)` : ''))
      setSel(new Set()); load()
    } catch (ex) { show(ex.message, true) } finally { setBusy(false) }
  }
 
  const research = async (l) => {
    show(`Researching ${l.company || l.email}…`)
    try { await api.research(l.id); load(); show('Research + pain points saved') }
    catch (ex) { show(ex.message, true) }
  }
 
  const bulkDelete = async () => {
    if (!sel.size) return
    if (!confirm(`Delete ${sel.size} selected leads?`)) return
    try { await api.bulkDeleteLeads([...sel]); setSel(new Set()); load(); show('Deleted') }
    catch (ex) { show(ex.message, true) }
  }
 
  const totalPages = Math.max(1, Math.ceil((data.total || 0) / perPage))
 
  return (
    <>
      <div className="records-intro card mb">
        <MiniOrb size={52} color="#0054FC" accent="#00BAFF" />
        <div style={{ flex: 1 }}>
          <b>Leads — your outreach queue</b>
          <p className="sm mut mt">
            <b><Counter value={stats?.total || 0} /></b> total leads · {stats?.contacted || 0} contacted ·
            &nbsp;{stats?.replied || 0} replied · {stats?.garbage || 0} in garbage.
            Server-side paging handles 50 000+ rows without slowdown.
          </p>
        </div>
        <button className="btn ghost small" onClick={() => setShowHow(s => !s)}>
          {showHow ? 'Hide' : 'How this works'} →
        </button>
      </div>
 
      {purgeDays !== null && (
        <div className="modal-veil" onClick={e => e.target === e.currentTarget && setPurgeDays(null)}>
          <div className="card">
            <b>Purge old completed / garbage leads</b>
            <p className="sm mut mt">
              Permanently deletes leads whose status is <b>completed</b> or <b>garbage</b> and haven't
              been touched in this many days — keeps the database lean at 50 000+ scale. Active,
              enrolled, or recently-replied leads are never touched by this.
            </p>
            <div className="field mt">
              <label>Older than (days)</label>
              <input type="number" min={1} value={purgeDays} onChange={e => setPurgeDays(e.target.value)} autoFocus />
            </div>
            <div className="row mt">
              <button className="btn danger" onClick={runPurge}>Purge now</button>
              <button className="btn ghost" onClick={() => setPurgeDays(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
 
      {blockedInfo && (
        <div className="modal-veil" onClick={e => e.target === e.currentTarget && setBlockedInfo(null)}>
          <div className="card">
            <b style={{ color: 'var(--hot)' }}>⚠ {blockedInfo.length} lead(s) owned by another agent</b>
            <p className="sm mut mt">
              While an agent is actively communicating with a lead, nobody else can take it.
              A paused agent, or one that stays silent past the ownership timeline
              (Settings → Lead ownership), releases its leads automatically.
            </p>
            <div className="mt" style={{ maxHeight: 240, overflowY: 'auto' }}>
              {blockedInfo.map(b => (
                <div key={b.lead_id} className="row between sm" style={{ padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
                  <span>{b.email}</span>
                  <span className="mut">
                    <b>{b.owned_by}</b> · {/^\d{4}-\d{2}-\d{2}/.test(b.unlock_at || '')
                      ? `unlocks ${new Date(b.unlock_at + 'Z').toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`
                      : (b.unlock_at || '')}
                  </span>
                </div>
              ))}
            </div>
            <button className="btn mt" onClick={() => setBlockedInfo(null)}>Got it</button>
          </div>
        </div>
      )}
 
      {showHow && (
        <div className="card mb explainer">
          <h3>How leads flow through the system</h3>
          <ol>
            <li><b>Upload</b> — drop an Excel or CSV. Any column layout works (company / name / email / website / country auto-detected). Duplicates are skipped, invalid mailboxes flagged red.</li>
            <li><b>Verify</b> — click "Verify mailboxes (SMTP)" to check which addresses actually exist before you send.</li>
            <li><b>Select</b> — tick the leads you want to reach out to. Filter by status or search by name/email.</li>
            <li><b>Pick a campaign & agent</b> — the agent decides tone, mailbox, signature, and reply style. Leave "Any agent" for round-robin.</li>
            <li><b>Enroll &amp; launch</b> — leads are bundled (20 / 30 / 40 / 50 — pick it before uploading) and emails go out one at a time, in order, spaced by the agent's outbound delay. <b>Auto-enroll on upload</b> does all of it the moment you drop a file in with a campaign + agent picked.</li>
            <li><b>Lead ownership</b> — a lead belongs to the agent it is talking to. While they communicate, no other agent can enroll it (the blocked list names the owner). <b>Pause an agent</b> and its leads become available at once; an agent that stays silent past the ownership timeline (Settings → Lead ownership, default 7 days) loses its leads too. A taken-over lead continues as follow-ups with the new agent — never a second cold email.</li>
            <li><b>Filter by agent</b> — the "Any agent" dropdown above both filters the list to that agent's leads AND sets who gets used for bulk Enroll &amp; launch.</li>
            <li><b>Watch replies</b> — inbound answers land in <b>Messages</b>. The agent auto-replies ~15 min later, KB-first. You can take over anytime.</li>
            <li><b>Housekeeping</b> — delete leads one-by-one, in bulk, or purge everything older than X days. Old completed leads never bog the DB down.</li>
          </ol>
        </div>
      )}
 
      {/* Live progress for the queued import / verification job. Adopts a job
          that is already running (page refresh) and shows the server's real
          phase + counters until it finishes. */}
      <ImportProgress job={imp.job} onDone={load} onDismiss={imp.reset} />

      {/* Toolbar */}
      <div className="row between mb wrap" style={{ gap: 10 }}>
        <div className="row" style={{ gap: 8 }}>
          <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv" onChange={upload} style={{ display: 'none' }} />
          <button className="btn" disabled={busy || imp.active} onClick={() => fileRef.current.click()}>
            <IconPlus /> {imp.active ? 'Import running…' : 'Upload Excel / CSV'}
          </button>
          <span className="sm mut" title="Batch size is set once on the Settings page (Email batch size) and applies to every upload, campaign and manual launch">
            bundles of {batchSize || '…'}
          </span>
          {!!sourceFiles.length && (
            <select value={sourceFile} onChange={e => {
              setSourceFile(e.target.value); setBatchFilter('')
            }} style={{ maxWidth: 190 }}
                    title="Work one Excel file at a time — Enroll all matching then launches only this file's leads">
              <option value="">All Excel files</option>
              {sourceFiles.map(f => <option key={f} value={f}>{f}</option>)}
            </select>
          )}
          {batchFilter && (
            <button className="btn ghost small" onClick={() => setBatchFilter('')}>
              Clear batch filter
            </button>
          )}
          <label className="chk" title="Pick a campaign AND an agent, then uploading enrolls every new lead and starts sending — one bundle at a time, in order">
            <input type="checkbox" checked={autoEnroll} onChange={e => setAutoEnroll(e.target.checked)} />
            Auto-enroll on upload
          </label>
          {autoEnroll && (!campaignId || !agentId) && (
            <span className="sm mut">
              needs {campaignId ? 'an agent' : 'a campaign + an agent'} in the toolbar →
            </span>
          )}
          <button className="btn ghost small" disabled={busy || imp.active} onClick={verifyMailboxes}
                  title="Resolve the MX record of every unverified lead's domain (one lookup per domain, not per lead)">
            {verifying || imp.job?.kind === 'verify' ? 'Verifying…' : 'Verify mailboxes'}
          </button>
          <button className="btn ghost small" disabled={busy} onClick={moveUnverifiedToGarbage}
                  title="Move every unverified lead into Trash (reviewable, not deleted)">
            Unverified → Trash
          </button>
          <button className="btn ghost small" disabled={busy} onClick={() => setPurgeDays('60')}>
            Purge old…
          </button>
          <button className="btn danger small" disabled={busy || (data.total || 0) === 0} onClick={deleteAll}>
            <IconTrash /> Delete all
          </button>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <select style={{ width: 160 }} value={agentId} onChange={e => setAgentId(e.target.value)}>
            <option value="">Any agent</option>
            {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <select style={{ width: 200 }} value={campaignId} onChange={e => setCampaignId(e.target.value)}>
            {campaigns.length === 0 && <option value="">No campaigns</option>}
            {campaigns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <button className="btn" disabled={!sel.size || !campaignId || busy || aiDisabled} onClick={enrollAndLaunch}
            title={aiDisabled ? 'OpenAI API key required — configure in Super Admin' : undefined}>
            {aiDisabled ? '🔑 Key required' : <><IconRocket /> Enroll &amp; launch {sel.size ? `(${sel.size})` : ''}</>}
          </button>
          <button className="btn ghost" disabled={!campaignId || !agentId || busy || (data.total || 0) === 0 || aiDisabled}
                  title={aiDisabled ? 'OpenAI API key required — configure in Super Admin' : 'Enroll EVERY lead matching the current filter (all pages), not just this page'}
                  onClick={enrollAllMatching}>
            <IconRocket /> Enroll all {data.total || 0} matching
          </button>
        </div>
      </div>
 
      {/* Filter bar */}
      <div className="records-filter card mb">
        <div className="filter-search">
          <IconSearch />
          <input placeholder="Search name, email or company…" value={q} onChange={e => setQ(e.target.value)} />
        </div>
        <div className="filter-group">
          <div className="seg">
            {['', 'new', 'enrolled', 'contacted', 'replied', 'garbage'].map(s => (
              <button key={s || 'all'} className={status === s ? 'on' : ''} onClick={() => setStatus(s)}>
                {s || 'All'}
              </button>
            ))}
          </div>
          <button className={`btn small ${unverifiedOnly ? '' : 'ghost'}`}
                  style={unverifiedOnly ? { background: 'var(--hot)' } : undefined}
                  onClick={() => setUnverifiedOnly(v => !v)}
                  title="Show only suspicious/unverified emails">
            ⚠ Suspicious (unverified) only
          </button>
          <button className={`btn small ${unassignedOnly ? '' : 'ghost'}`}
                  style={unassignedOnly ? { background: 'var(--brand, #0054FC)', color: '#fff' } : undefined}
                  onClick={() => setUnassignedOnly(v => !v)}
                  title="Show only leads not yet assigned to any agent — then 'Enroll all matching' to assign them all at once">
            Unassigned only
          </button>
          <div className="seg">
            {[['', 'Agent silent'], ['needs_human_only', 'Needs a human'],
              ['not_interested_only', 'Not interested']].map(([k, label]) => (
              <button key={k || 'none'} className={humanOnly === k ? 'on' : ''}
                      onClick={() => setHumanOnly(humanOnly === k ? '' : k)}
                      title={k === 'needs_human_only'
                        ? 'The agent stopped on these: they asked about price, a contract, legal, security or who the company is. The thread stays in Messages so you can answer it.'
                        : k === 'not_interested_only'
                          ? 'They said they are not interested. The agent sent nothing back, the lead went Cold and sits in Trash — the conversation stays in Messages. They get deleted after the retention window.'
                          : 'Show every lead again'}>
                {label}
              </button>
            ))}
          </div>
          {sel.size > 0 && (
            <div className="row" style={{ gap: 6, alignItems: 'center' }}>
              <select value={bulkAgent} onChange={e => setBulkAgent(e.target.value)}
                      style={{ width: 130 }} title="Assign all selected leads to this agent at once">
                <option value="">Assign agent…</option>
                {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
              <button className="btn small" disabled={!bulkAgent || !campaignId || busy || aiDisabled}
                      title={aiDisabled ? 'OpenAI API key required — configure in Super Admin' : undefined}
                      onClick={enrollSelectedWith}>
                Enroll {sel.size} with agent
              </button>
            </div>
          )}
          {sel.size > 0 && (
            <button className="btn small" onClick={bulkGarbage} disabled={busy}
                    title="Move the selected leads straight to Trash">
              Move {sel.size} → Trash
            </button>
          )}
          {sel.size > 0 && (
            <button className="btn danger small" onClick={bulkDelete}>
              Delete {sel.size} selected
            </button>
          )}
        </div>
      </div>
 
      <div className="card" style={{ padding: 0, overflow: 'auto' }}>
        {data.items.length === 0
          ? <div className="empty">No leads match — upload a sheet or clear filters.</div>
          : (
            <table>
              <thead>
                <tr>
                  <th style={{ width: 34 }}>
                    <input type="checkbox" style={{ width: 16 }}
                           checked={launchable.length > 0 && sel.size === launchable.length}
                           onChange={toggleAll} />
                  </th>
                  <th>Person</th><th>Company / Domain</th><th>MX Record</th><th>Country</th><th>Agent</th>
                  <th>Status</th><th>Temp</th><th>Research</th><th></th>
                </tr>
              </thead>
              <tbody>
                {data.items.map(l => (
                  <tr key={l.id} style={l.email_verified === false ? { background: '#fef2f2' } : undefined}>
                    <td>{['new', 'enrolled'].includes(l.status)
                      ? <input type="checkbox" style={{ width: 16 }} checked={sel.has(l.id)} onChange={() => toggleOne(l.id)} />
                      : null}</td>
                    <td>
                      <b>{l.name || '—'}</b>
                      <div className="sm mut">{l.email}</div>
                    </td>
                    <td>{l.company || '—'}<div className="sm mut ellipsis">{l.email ? l.email.split('@')[1] : l.website}</div></td>
                    <td>
                      {l.email_verified === false
                        ? <span className="pill" style={{ background: '#fee2e2', color: '#b91c1c' }} title="No MX record found — domain may not accept email">⚠ Suspicious (No MX)</span>
                        : <span className="pill" style={{ background: '#dcfce7', color: '#166534' }}>✓ MX OK</span>}
                    </td>
                    <td>{l.country || '—'}</td>
                    <td>
                      {l.agent_name
                        ? <div className="sm">{l.status === 'enrolled'
                            ? <span>✅ enrolled with <b>{l.agent_name}</b></span>
                            : <span><b>{l.agent_name}</b> currently</span>}</div>
                        : <span className="mut sm">unassigned</span>}
                      {l.locked_until && (
                        <div className="sm mut" title="Another agent already emailed this lead today — it unlocks then">
                          🔒 next available {new Date(l.locked_until + 'Z').toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                        </div>
                      )}
                        {['new', 'enrolled', 'contacted'].includes(l.status) && (
                        <div className="row" style={{ gap: 4, marginTop: 4 }}>
                          <select style={{ width: 110, padding: '4px 6px', fontSize: 12 }}
                                  value={rowAgentSel[l.id] ?? ''}
                                  onChange={e => setRowAgentSel(s => ({ ...s, [l.id]: e.target.value }))}>
                            <option value="">Pick agent…</option>
                            {agents
                              .filter(a => !l.locked_until || a.name === l.agent_name)
                              .map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                          </select>
                          <button className="btn ghost small" disabled={!rowAgentSel[l.id]}
                                  onClick={() => enrollOneWithAgent(l, rowAgentSel[l.id])}>
                            Enroll
                          </button>
                        </div>
                      )}
                    </td>
                    <td>
                      <div className="row" style={{ gap: 4, flexWrap: 'wrap' }}>
                        <span className={`pill ${l.status === 'replied' ? 'ok' : l.status === 'contacted' ? 'blue' : 'gray'}`}>{l.status}</span>
                        {l.needs_human && (
                          <span className="pill" style={{ background: '#fef3c7', color: '#b45309' }}
                                title={(l.needs_human_reason || 'A human has to answer this').replace(/^needs-human:/, '')}>
                            Human needed
                          </span>
                        )}
                        {l.not_interested && (
                          <span className="pill" style={{ background: '#e5e7eb', color: '#4b5563' }}
                                title={l.not_interested_note || 'Said not interested — agent is silent, deleted after the retention window'}>
                            Not interested
                          </span>
                        )}
                      </div>
                    </td>
                    <td><span className={`pill ${l.temperature}`}>{l.temperature}</span></td>
                    <td className="sm mut" style={{ maxWidth: 260 }}>
                      {l.pain_points ? l.pain_points.slice(0, 100) + '…' : <i>none yet</i>}
                    </td>
                    <td>
                      <div className="row" style={{ gap: 4 }}>
                        <button className="btn ghost small" disabled={aiDisabled} onClick={() => research(l)}
                          title={aiDisabled ? 'OpenAI API key required — configure in Super Admin' : undefined}>
                          {aiDisabled ? '🔑 Key required' : 'Research'}
                        </button>
                        <button className="icon-btn danger" onClick={async () => { await api.deleteLead(l.id); load() }}><IconTrash /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </div>
 
      <div className="pager mt">
        <button className="btn ghost small" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
        <span className="sm mut">Page {data.page} of {totalPages} · {data.total} leads</span>
        <button className="btn ghost small" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next →</button>
      </div>

      <Toast toast={toast} />
    </>
  )
}