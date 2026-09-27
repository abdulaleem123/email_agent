import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import MiniOrb from '../MiniOrb.jsx'
import { Toast, useToast } from '../App.jsx'
import Counter from '../Counter.jsx'
import {
  IconAlert, IconTrash, IconRefresh, IconSearch, IconInbox, IconSend,
  IconFilter, IconFlag,
} from '../Icons.jsx'

/**
 * ESCALATION — the "a human has to decide" queue.
 *
 * Everything here is mail the agent must NOT answer by itself, parked away
 * from Mail Records and away from Garbage:
 *   · meeting / scheduling links  (Calendly, Cal.com, Zoom, Meet, a booking bot)
 *   · promotions / marketing blasts
 *   · role-account replies         (info@, support@, noreply@ …)
 *   · system notifications         (Zoho / Hostinger technical mail)
 *   · delivery failures            (bounces, undeliverable, DSNs)
 *   · outbound we refused to send  (blocked address, unverified, send failure)
 *
 * The related lead is auto-paused — no follow-ups, no auto-replies — and the
 * whole queue self-purges after 30 days so it never becomes a 50k-row dump.
 * "Resume agent" on a row clears the pause and drops the escalation.
 */
const PER_PAGE = 25
const REASON_TONE = {
  'meeting-link': 'blue',
  'promotion': 'gray',
  'delivery-failed': 'ok',
  'role-account': 'gray',
  'system-notification': 'gray',
  'disposable-address': 'gray',
  'blocked-outbound': 'hot',
  'unverified-recipient': 'hot',
  'send-failed': 'hot',
}

export default function Escalations() {
  const [data, setData] = useState({ items: [], total: 0, page: 1, pages: 1 })
  const [summary, setSummary] = useState(null)
  const [page, setPage] = useState(1)
  const [reason, setReason] = useState('')
  const [direction, setDirection] = useState('')
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [sel, setSel] = useState(new Set())
  const [opened, setOpened] = useState(null)
  const [full, setFull] = useState(null)
  const [busy, setBusy] = useState(false)
  const [newCount, setNewCount] = useState(0)
  const [toast, show] = useToast()
  const sinceId = useRef(0)

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 300)
    return () => clearTimeout(t)
  }, [q])

  const load = useCallback(async () => {
    setBusy(true)
    const params = new URLSearchParams({ page, per_page: PER_PAGE })
    if (reason) params.set('reason', reason)
    if (direction) params.set('direction', direction)
    if (debouncedQ) params.set('q', debouncedQ)
    try {
      const [d, s] = await Promise.all([
        api.escalations(params.toString()),
        api.escalationsSummary(),
      ])
      setData(d)
      setSummary(s)
      setSel(new Set())
      if (Array.isArray(d.items) && d.items.length)
        sinceId.current = Math.max(sinceId.current, ...d.items.map(r => r.id || 0))
    } catch (e) { show(e.message, true) } finally { setBusy(false) }
  }, [page, reason, direction, debouncedQ, show])

  useEffect(() => { load() }, [load])
  useEffect(() => { setPage(1) }, [reason, direction, debouncedQ])
  useEffect(() => { setNewCount(0) }, [page, reason, direction, debouncedQ])

  // Full body is only fetched when a row is opened.
  useEffect(() => {
    let dead = false
    setFull(null)
    if (!opened) return
    api.escalation(opened).then(r => { if (!dead) setFull(r) }).catch(() => {})
    return () => { dead = true }
  }, [opened])

  // Real-time badge — something new needs a human?
  useEffect(() => {
    const poll = async () => {
      try {
        const f = await api.escalationFeed(sinceId.current)
        if (f?.latest_id) sinceId.current = Math.max(sinceId.current, f.latest_id)
        if (f?.new) setNewCount(n => n + f.new)
      } catch { /* silent */ }
    }
    const t = setInterval(poll, 10000)
    return () => clearInterval(t)
  }, [])

  const toggleAll = () => setSel(s => (s.size === data.items.length ? new Set() : new Set(data.items.map(r => r.id))))
  const toggleOne = (id) => setSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })

  const resume = async (row) => {
    if (!confirm(`Let the agent contact ${row.lead_email || row.from_addr} again and drop this escalation?`)) return
    try { await api.resumeEscalation(row.id); show('Agent resumed on this lead'); load() }
    catch (e) { show(e.message, true) }
  }

  const removeOne = async (row) => {
    if (!confirm('Delete this escalation? The lead stays auto-paused until the row is gone or you resume it.')) return
    try { await api.deleteEscalation(row.id); show('Deleted'); load() }
    catch (e) { show(e.message, true) }
  }

  const bulkDelete = async () => {
    if (!sel.size) return
    if (!confirm(`Delete ${sel.size} escalation(s)?`)) return
    try { const r = await api.bulkDeleteEscalations([...sel]); show(`Deleted ${r.deleted}`); load() }
    catch (e) { show(e.message, true) }
  }

  const clearAll = async () => {
    if (!confirm(`Permanently delete all ${summary?.total || 0} escalations? Leads stay auto-paused.`)) return
    try { const r = await api.clearEscalations(); show(`Cleared ${r.deleted}`); setPage(1); load() }
    catch (e) { show(e.message, true) }
  }

  const purgeNow = async () => {
    const days = prompt('Delete escalations older than how many days?', String(summary?.retention_days || 30))
    if (!days) return
    const n = parseInt(days, 10)
    if (!Number.isFinite(n) || n < 1) { show('Enter a positive number', true); return }
    try { const r = await api.purgeEscalations(n); show(`Purged ${r.deleted} older than ${n}d`); load() }
    catch (e) { show(e.message, true) }
  }

  const reasons = summary?.by_reason || {}
  const reasonChips = useMemo(
    () => Object.entries(reasons).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]),
    [reasons],
  )
  const totalPaused = summary?.agents_auto_paused || 0
  const totalPages = Math.max(1, data.pages || 1)
  const pageList = Array.from({ length: totalPages }, (_, i) => i + 1)
    .filter(p => p === 1 || p === totalPages || Math.abs(p - page) <= 2)

  return (
    <>
      <div className="records-intro card mb">
        <MiniOrb size={52} color="#d97706" accent="#b91c1c" />
        <div style={{ flex: 1 }}>
          <b>Escalation — mail only a human should touch</b>
          <p className="sm mut mt">
            <b><Counter value={data.total || 0} /></b> item(s) waiting ·{' '}
            <b><Counter value={totalPaused} /></b> lead(s) with the agent auto-paused.
            Meeting links, promotions, <code>info@</code>/<code>support@</code>/<code>noreply@</code> replies,
            system notifications, delivery failures and any outbound we refused to send —{' '}
            <b>no email is sent and no auto-reply is generated</b> for any of these.
            They stay out of Mail Records and out of Garbage, and delete themselves after{' '}
            <b>{summary?.retention_days || 30} days</b>.
          </p>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn ghost small" onClick={load} title="Refresh">
            <IconRefresh /> Refresh
            {newCount > 0 && (
              <span style={{ marginLeft: 6, background: '#b91c1c', color: '#fff', borderRadius: 99, padding: '1px 7px', fontSize: 11, fontWeight: 700 }}>
                {newCount} new
              </span>
            )}
          </button>
          <button className="btn ghost small" onClick={purgeNow} title={`Auto-purges at ${summary?.retention_days || 30} days — this does it now`}>
            <IconTrash /> Purge old…
          </button>
          <button className="btn danger small" disabled={!data.total} onClick={clearAll}>Clear all</button>
        </div>
      </div>

      {/* Reason chips */}
      {reasonChips.length > 0 && (
        <div className="records-agent-strip mb">
          <div className={`records-agent-card ${reason === '' ? 'on' : ''}`} onClick={() => setReason('')}>
            <div className="agent-name"><IconAlert style={{ width: 13, height: 13, verticalAlign: -2 }} /> All escalations</div>
            <div className="agent-stats"><span><Counter value={summary?.total || 0} /></span></div>
          </div>
          {reasonChips.map(([g, n]) => (
            <div key={g} className={`records-agent-card ${reason === g ? 'on' : ''}`} onClick={() => setReason(g)}>
              <div className="agent-name">{summary?.labels?.[g] || g}</div>
              <div className="agent-stats"><span><Counter value={n} /></span></div>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="records-filter card mb">
        <div className="filter-search">
          <IconSearch />
          <input placeholder="Search sender, subject, body or reason…" value={q} onChange={e => setQ(e.target.value)} />
        </div>
        <div className="filter-group">
          <IconFilter />
          <div className="seg">
            <button className={direction === '' ? 'on' : ''} onClick={() => setDirection('')}>All</button>
            <button className={direction === 'in' ? 'on' : ''} onClick={() => setDirection('in')}>Received</button>
            <button className={direction === 'out' ? 'on' : ''} onClick={() => setDirection('out')}>Would-have-sent</button>
          </div>
        </div>
        <div className="row" style={{ marginLeft: 'auto', gap: 8 }}>
          {sel.size > 0 && (
            <button className="btn danger small" onClick={bulkDelete}>Delete {sel.size} selected</button>
          )}
          <span className="sm mut">{data.total} total</span>
        </div>
      </div>

      {/* Table */}
      <div className="card records-table-card">
        {busy && data.items.length === 0 && <div className="empty">Loading escalations…</div>}
        {!busy && data.items.length === 0 && (
          <div className="empty">
            Nothing escalated — no meeting links, promotions, role-account replies, delivery failures or blocked sends.
          </div>
        )}
        {data.items.length > 0 && (
          <table className="records-table">
            <thead>
              <tr>
                <th style={{ width: 44 }}>
                  <input type="checkbox" style={{ width: 16 }}
                         checked={sel.size === data.items.length && data.items.length > 0}
                         onChange={toggleAll} />
                </th>
                <th>Reason</th>
                <th>Direction</th>
                <th>Contact</th>
                <th>Agent</th>
                <th>Batch</th>
                <th>Subject</th>
                <th>When</th>
                <th style={{ width: 92 }}></th>
              </tr>
            </thead>
            <tbody>
              {data.items.map(r => (
                <React.Fragment key={r.id}>
                  <tr className={`record-row ${opened === r.id ? 'open' : ''}`}
                      onClick={() => setOpened(opened === r.id ? null : r.id)}>
                    <td onClick={e => e.stopPropagation()}>
                      <input type="checkbox" style={{ width: 16 }} checked={sel.has(r.id)} onChange={() => toggleOne(r.id)} />
                    </td>
                    <td>
                      <span className={`pill ${REASON_TONE[r.reason_group] || 'gray'}`}>
                        {r.reason_label || r.reason_group || 'escalated'}
                      </span>
                      {r.agent_paused && (
                        <div className="sm mut" style={{ marginTop: 4 }}>⏸ agent auto-paused</div>
                      )}
                    </td>
                    <td>
                      <span className={`dir-pill ${r.direction}`}>
                        {r.direction === 'in' ? <IconInbox /> : <IconSend />}
                      </span>
                    </td>
                    <td>
                      <b className="ellipsis">{r.lead_name || r.lead_email || '—'}</b>
                      <div className="sm mut ellipsis">{r.lead_email || r.from_addr}</div>
                      {r.lead_company && <div className="sm mut ellipsis">{r.lead_company}</div>}
                    </td>
                    <td className="sm">{r.agent_name || <span className="mut">system</span>}</td>
                    <td>
                      {r.batch_no && <span className="pill">{r.batch_no}</span>}
                      {r.campaign_name && <div className="sm mut ellipsis">{r.campaign_name}</div>}
                    </td>
                    <td>
                      <span className="ellipsis" style={{ maxWidth: 260 }}>
                        {r.subject || <span className="mut">(no subject)</span>}
                      </span>
                      {r.preview && <div className="sm mut ellipsis" style={{ maxWidth: 260 }}>{r.preview}</div>}
                    </td>
                    <td className="sm mut">{new Date(r.created_at + 'Z').toLocaleString()}</td>
                    <td onClick={e => e.stopPropagation()}>
                      <div className="row" style={{ gap: 4 }}>
                        <button className="btn ghost small" onClick={() => resume(r)} title="Clear the auto-pause so the agent may contact this lead again">
                          <IconFlag /> Resume
                        </button>
                        <button className="icon-btn danger" onClick={() => removeOne(r)} title="Delete">
                          <IconTrash />
                        </button>
                      </div>
                    </td>
                  </tr>
                  {opened === r.id && (
                    <tr className="record-detail">
                      <td colSpan={9}>
                        <div className="sm mut mb" style={{ paddingBottom: 6 }}>
                          <b>Reason:</b> {r.reason || '—'} · <b>From:</b> {r.from_addr || '—'} ·
                          {' '}<b>Lead status:</b> {r.lead_status || '—'} ·
                          {' '}<b>Agent:</b> {r.agent_name || 'system (auto-paused)'}
                        </div>
                        <div className="record-body">
                          {!full ? <div className="mut sm">Loading full message…</div>
                            : (full.body || full.preview
                              ? <pre>{full.body || full.preview}</pre>
                              : <div className="mut sm">(no body stored)</div>)}
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

      {/* Pagination — built for 50k+ rows, never renders more than 7 buttons */}
      {totalPages > 1 && (
        <div className="pagination">
          <button disabled={page === 1} onClick={() => setPage(p => p - 1)}>‹ Prev</button>
          {pageList.map((p, i) => (
            <React.Fragment key={p}>
              {i > 0 && pageList[i - 1] !== p - 1 && <span className="mut">…</span>}
              <button className={p === page ? 'on' : ''} onClick={() => setPage(p)}>{p}</button>
            </React.Fragment>
          ))}
          {pageList[pageList.length - 1] < totalPages && <span className="mut">…</span>}
          <button disabled={page === totalPages} onClick={() => setPage(p => p + 1)}>Next ›</button>
          <span className="sm mut" style={{ marginLeft: 10 }}>
            Page {page} of {totalPages} · {data.total} rows
          </span>
        </div>
      )}
      <Toast toast={toast} />
    </>
  )
}
