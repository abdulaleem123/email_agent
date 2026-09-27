import React, { useEffect, useMemo, useState, useCallback, useRef } from 'react'
import { api } from '../api.js'
import MiniOrb from '../MiniOrb.jsx'
import { Toast, useToast } from '../App.jsx'
import Counter from '../Counter.jsx'
import { IconArchive, IconTrash, IconRefresh, IconSearch, IconMail, IconSend, IconInbox, IconFilter } from '../Icons.jsx'

/**
 * Mail Records — one paginated table of EVERY email sent/received by any
 * agent. Designed for 50k+ rows: hard page size, keyset-friendly filters,
 * agent-wise breakdown card. Every row has a per-row delete; a bulk purge
 * button lets you drop everything older than N days at once.
 * Real-time: polls /feed/new every 8 seconds and prepends new records.
 */
export default function MailRecords() {
  const [page, setPage] = useState(1)
  const [perPage] = useState(25)
  const [direction, setDirection] = useState('')       // '' | 'in' | 'out'
  const [agentId, setAgentId] = useState('')
  const [sourceFile, setSourceFile] = useState('')     // the Excel a lead came from
  const [batchId, setBatchId] = useState('')           // one 20/30/40/50 batch
  const [showBatches, setShowBatches] = useState(false)
  const [batches, setBatches] = useState([])
  const [campaigns, setCampaigns] = useState([])
  const [enrollCampaign, setEnrollCampaign] = useState('')
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [includeSpam, setIncludeSpam] = useState(false)

  const [data, setData] = useState({ items: [], total: 0, page: 1, per_page: 25 })
  const [agents, setAgents] = useState([])
  const [summary, setSummary] = useState([])
  const [busy, setBusy] = useState(false)
  const [opened, setOpened] = useState(null)          // row expanded
  const [newCount, setNewCount] = useState(0)          // badge for real-time arrivals
  const [toast, show] = useToast()
  const sinceId = useRef(0)                            // highest seen mail record id

  // debounce search input so we don't spam the API on every keystroke
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 300)
    return () => clearTimeout(t)
  }, [q])

  const load = useCallback(async () => {
    setBusy(true)
    const params = new URLSearchParams({ page, per_page: perPage })
    if (direction) params.set('direction', direction)
    if (agentId) params.set('agent_id', agentId)
    if (debouncedQ) params.set('q', debouncedQ)
    if (sourceFile) params.set('source_file', sourceFile)
    if (batchId) params.set('batch_id', batchId)
    if (includeSpam) params.set('include_spam', 'true')
    try {
      const d = await api.mailRecords(params.toString())
      setData(d)
      // track the highest id we've loaded so the poll knows what's 'new'
      if (Array.isArray(d.items) && d.items.length)
        sinceId.current = Math.max(sinceId.current, ...d.items.map(r => r.id || 0))
      setNewCount(0)
    } catch (e) { show(e.message, true) } finally { setBusy(false) }
  }, [page, perPage, direction, agentId, debouncedQ, sourceFile, batchId, includeSpam, show])

  const loadBatches = useCallback(async () => {
    try {
      const d = await api.mailRecordBatches({ limit: 200 })
      setBatches(d?.items || [])
    } catch { /* the table still works without the batch panel */ }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { loadBatches() }, [loadBatches])
  useEffect(() => { api.agents().then(setAgents).catch(() => {}) }, [])
  useEffect(() => { api.campaigns().then(cs => {
    setCampaigns(cs || [])
    if (cs?.length) setEnrollCampaign(String(cs[0].id))
  }).catch(() => {}) }, [])
  useEffect(() => { api.mailRecordsAgentSummary().then(setSummary).catch(() => {}) }, [])

  // Real-time feed poll — every 8 seconds, check for new mail records
  useEffect(() => {
    const poll = async () => {
      try {
        const fresh = await api.mailRecordsFeed({ since_id: sinceId.current, agent_id: agentId || undefined })
        if (Array.isArray(fresh) && fresh.length) {
          sinceId.current = Math.max(sinceId.current, ...fresh.map(r => r.id || 0))
          setNewCount(n => n + fresh.length)
        }
      } catch { /* silent */ }
    }
    const t = setInterval(poll, 8000)
    return () => clearInterval(t)
  }, [agentId])

  // reset to page 1 whenever a filter changes
  useEffect(() => { setPage(1) }, [direction, agentId, debouncedQ, includeSpam, sourceFile, batchId])

  const totalPages = Math.max(1, Math.ceil((data.total || 0) / perPage))

  // Batches grouped by the Excel they came from, so "this sheet sent as 6
  // batches of 50" is one glance instead of six separate lookups.
  const batchesByFile = useMemo(() => {
    const out = new Map()
    for (const b of batches) {
      const key = b.source_file || '(no file recorded)'
      if (!out.has(key)) out.set(key, [])
      out.get(key).push(b)
    }
    return out
  }, [batches])

  const pickBatch = (b) => {
    setBatchId(String(batchId) === String(b.id) ? '' : String(b.id))
    setSourceFile('')
    if (b.source_file) loadBatches()
  }

  const enrollBatch = async (b) => {
    if (!enrollCampaign) { show('Pick a campaign first', true); return }
    const camp = campaigns.find(c => String(c.id) === String(enrollCampaign))
    const label = `${b.source_file || 'this file'} ${b.number} (${b.total} leads)`
    if (!confirm(`Enroll ${label} into "${camp?.name || 'the campaign'}"? The batch size on Settings decides how it is re-batched.`)) return
    try {
      const r = await api.enrollBatches([b.id], +enrollCampaign, camp?.agent_id || null)
      show(`Enrolled ${r.enrolled} leads in ${r.batches?.length || 0} batch(es)`
        + (r.blocked_count ? ` · ${r.blocked_count} skipped (already contacted / locked)` : ''))
      loadBatches(); load()
    } catch (e) { show(e.message, true) }
  }

  const removeOne = async (id) => {
    if (!confirm('Delete this record permanently?')) return
    try { await api.deleteMailRecord(id); show('Deleted'); load() }
    catch (e) { show(e.message, true) }
  }

  const exportReport = async () => {
    setBusy(true)
    try {
      const params = {}
      if (direction) params.direction = direction
      if (agentId) params.agent_id = agentId
      if (debouncedQ) params.q = debouncedQ
      if (includeSpam) params.include_spam = 'true'
      await api.mailRecordsExport(params)
      show('Excel report downloaded — check your Downloads folder')
    } catch (e) { show(e.message, true) } finally { setBusy(false) }
  }

  const purgeOld = async () => {
    const days = prompt('Purge every mail record older than how many days?', '90')
    if (!days) return
    const n = parseInt(days, 10)
    if (!Number.isFinite(n) || n < 1) { show('Enter a positive number', true); return }
    if (!confirm(`Permanently delete every record older than ${n} days? This can't be undone.`)) return
    try {
      const r = await api.purgeMailOlderThan(n)
      show(`Purged ${r.deleted ?? 0} records`)
      load()
      api.mailRecordsAgentSummary().then(setSummary).catch(() => {})
    } catch (e) { show(e.message, true) }
  }

  const totalSent = useMemo(() => summary.reduce((s, a) => s + (a.sent || 0), 0), [summary])
  const totalRecv = useMemo(() => summary.reduce((s, a) => s + (a.received || 0), 0), [summary])

  return (
    <>
      <div className="records-intro card mb">
        <MiniOrb size={52} color="#0054FC" accent="#00BAFF" />
        <div style={{ flex: 1 }}>
          <b>Mail Records — every email, every agent, one place</b>
          <p className="sm mut mt">
            Full audit trail of {' '}
            <b><Counter value={data.total || 0} /></b> messages — inbound + outbound + spam.
            This is also where <b>batch &amp; campaign bookkeeping</b> lives: which send belonged to which
            batch, and the progress of every run. Search by sender/subject, filter by agent or direction,
            delete row-by-row, or bulk-purge old records. Optimized for 50 000+ rows: server-side paging,
            no browser slowdown. Mail a human must judge (meeting links, promotions, role accounts,
            delivery failures) is <b>not</b> stored here — see <b>Escalation</b>.
          </p>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn ghost small" onClick={load} title="Refresh">
            <IconRefresh /> Refresh
            {newCount > 0 && <span style={{ marginLeft: 6, background: '#2563eb', color: '#fff', borderRadius: 99, padding: '1px 7px', fontSize: 11, fontWeight: 700 }}>{newCount} new</span>}
          </button>
          <button className="btn ghost small" onClick={exportReport} title="Download an Excel sheet — which send went to which batch & campaign">
            <IconArchive /> Export report (Excel)
          </button>
          <button className="btn danger small" onClick={purgeOld}><IconTrash /> Purge old…</button>
        </div>
      </div>

      {/* Agent breakdown row */}
      <div className="records-agent-strip mb">
        <div
          className={`records-agent-card ${agentId === '' ? 'on' : ''}`}
          onClick={() => setAgentId('')}
        >
          <div className="agent-name">All agents</div>
          <div className="agent-stats">
            <span><IconSend /> <Counter value={totalSent} /></span>
            <span><IconInbox /> <Counter value={totalRecv} /></span>
          </div>
        </div>
        {summary.map(a => (
          <div key={a.agent_id ?? 'sys'}
               className={`records-agent-card ${String(agentId) === String(a.agent_id) ? 'on' : ''}`}
               onClick={() => setAgentId(String(a.agent_id ?? ''))}>
            <div className="agent-name">{a.name || (a.agent_id ? `#${a.agent_id}` : 'system')}</div>
            <div className="agent-stats">
              <span><IconSend /> <Counter value={a.sent || 0} /></span>
              <span><IconInbox /> <Counter value={a.received || 0} /></span>
            </div>
          </div>
        ))}
      </div>

      {/* Batches: 20/30/40/50 at a time, per Excel file. Collapsed by default
          because it can be a long list, but it is where batch-wise enrollment
          and "which sheet did this go out with" live. */}
      <div className="card mb">
        <div className="row between wrap" style={{ gap: 8 }}>
          <button className="btn ghost small" onClick={() => setShowBatches(v => !v)}>
            {showBatches ? '▾' : '▸'} Batches by file ({batches.length})
          </button>
          <div className="row wrap" style={{ gap: 8 }}>
            {(sourceFile || batchId) && (
              <button className="btn ghost small" onClick={() => { setSourceFile(''); setBatchId('') }}>
                Clear batch filter
              </button>
            )}
            <select value={enrollCampaign} onChange={e => setEnrollCampaign(e.target.value)}
                    title="Campaign used when you enroll a batch from the list below">
              <option value="">Campaign for batch enroll…</option>
              {campaigns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
        </div>

        {(batchId || sourceFile) && (
          <div className="sm mut mt">
            Showing {batchId ? `batch #${batchId}` : `everything from ${sourceFile}`}
          </div>
        )}

        {showBatches && (
          <div className="mt" style={{ maxHeight: 340, overflowY: 'auto' }}>
            {!batches.length && <div className="empty">No batches yet — they are created when a sheet is imported or a campaign is launched.</div>}
            {[...batchesByFile.entries()].map(([file, list]) => (
              <div key={file} style={{ marginBottom: 14 }}>
                <div className="row between" style={{ gap: 8 }}>
                  <b className="sm ellipsis" title={file}>{file}</b>
                  <button className="btn ghost small"
                          onClick={() => { setSourceFile(sourceFile === file ? '' : file); setBatchId('') }}
                          title="Filter the table to this Excel">
                    {sourceFile === file ? 'Clear' : 'Filter table'}
                  </button>
                </div>
                <div className="sm mut">{list.length} batch(es) · {list.reduce((s, b) => s + (b.total || 0), 0)} leads</div>
                <div className="row wrap mt" style={{ gap: 6 }}>
                  {list.map(b => (
                    <div key={b.id}
                         className={`pill ${String(batchId) === String(b.id) ? 'ok' : ''}`}
                         style={{ cursor: 'pointer' }}
                         onClick={() => pickBatch(b)}
                         title="Click to filter the table to this batch">
                      B#{b.number} · {b.total}
                      {b.sent ? ` · ${b.sent} sent` : ''}
                      {b.status === 'completed' ? ' ✓' : b.status === 'paused' ? ' ⏸' : ''}
                    </div>
                  ))}
                  <button className="btn ghost small" onClick={() => enrollBatch(list[0])}
                          title="Enroll the first batch of this file — every batch of the file works the same way">
                    Enroll batch B#{list[0].number}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Filter bar */}
      <div className="records-filter card mb">
        <div className="filter-search">
          <IconSearch />
          <input placeholder="Search sender, subject, or body…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="filter-group">
          <IconFilter />
          <div className="seg">
            <button className={direction === '' ? 'on' : ''} onClick={() => setDirection('')}>All</button>
            <button className={direction === 'out' ? 'on' : ''} onClick={() => setDirection('out')}>Sent</button>
            <button className={direction === 'in' ? 'on' : ''} onClick={() => setDirection('in')}>Received</button>
          </div>
          <label className="chk">
            <input type="checkbox" checked={includeSpam} onChange={(e) => setIncludeSpam(e.target.checked)} />
            <span>Include spam</span>
          </label>
        </div>
      </div>

      {/* Table */}
      <div className="card records-table-card">
        {busy && data.items.length === 0 && <div className="empty">Loading records…</div>}
        {!busy && data.items.length === 0 && <div className="empty">No records match — try clearing filters.</div>}
        {data.items.length > 0 && (
          <table className="records-table">
            <thead>
              <tr>
                <th style={{ width: 44 }}></th>
                <th>Direction</th>
                <th>Agent</th>
                <th>Contact</th>
                <th>Batch / File / Campaign</th>
                <th>Subject</th>
                <th>When</th>
                <th style={{ width: 44 }}></th>
              </tr>
            </thead>
            <tbody>
              {data.items.map(r => (
                <React.Fragment key={r.id}>
                  <tr className={`record-row ${opened === r.id ? 'open' : ''}`} onClick={() => setOpened(opened === r.id ? null : r.id)}>
                    <td>
                      <span className={`dir-pill ${r.direction}`}>
                        {r.direction === 'in' ? <IconInbox /> : <IconSend />}
                      </span>
                    </td>
                    <td><span className="pill ok">{r.direction === 'in' ? 'Inbound' : 'Outbound'}</span></td>
                    <td>{r.agent_name || <span className="mut">system</span>}</td>
                    <td>
                      <b className="ellipsis">{r.lead_name || r.contact_email || '—'}</b>
                      <div className="sm mut ellipsis">{r.contact_email}</div>
                    </td>
                    <td>
                      {r.batch_no && (
                        <span className="pill" style={{ cursor: batchId ? 'pointer' : 'default' }}
                              onClick={e => { e.stopPropagation(); if (r.batch_id) setBatchId(String(batchId) === String(r.batch_id) ? '' : String(r.batch_id)) }}>
                          {r.batch_no}{r.batch_size ? ` · ${r.batch_sent}/${r.batch_size}` : ''}
                        </span>
                      )}
                      {r.source_file && <div className="sm mut ellipsis" title={r.source_file}>{r.source_file}</div>}
                      {r.campaign_name && <div className="sm mut ellipsis">{r.campaign_name}</div>}
                    </td>
                    <td>
                      <span className="ellipsis">{r.subject || <span className="mut">(no subject)</span>}</span>
                      {r.is_spam && (
                        <div className="pill" style={{ background: '#fee2e2', color: '#b91c1c', marginTop: 4, width: 'fit-content' }}>
                          {r.spam_reason || 'spam'}
                        </div>
                      )}
                    </td>
                    <td className="sm mut">{new Date(r.created_at + 'Z').toLocaleString()}</td>
                    <td>
                      <button className="icon-btn danger" onClick={(e) => { e.stopPropagation(); removeOne(r.id) }} title="Delete">
                        <IconTrash />
                      </button>
                    </td>
                  </tr>
                  {opened === r.id && (
                    <tr className="record-detail">
                      <td colSpan={8}>
                        <div className="record-body">
                          {r.body ? <pre>{r.body}</pre> : <div className="mut sm">(no body stored)</div>}
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pager */}
      <div className="pager mt">
        <button className="btn ghost small" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
        <span className="sm mut">Page {data.page} of {totalPages} · {data.total} records</span>
        <button className="btn ghost small" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next →</button>
      </div>
      <Toast toast={toast} />
    </>
  )
}