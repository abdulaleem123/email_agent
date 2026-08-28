// import React, { useEffect, useMemo, useState, useCallback } from 'react'
// import { api } from '../api.js'
// import { Toast, useToast } from '../App.jsx'
// import Counter from '../Counter.jsx'
// import { IconArchive, IconTrash, IconRefresh, IconSearch, IconMail, IconSend, IconInbox, IconFilter } from '../Icons.jsx'

// /**
//  * Mail Records — one paginated table of EVERY email sent/received by any
//  * agent. Designed for 50k+ rows: hard page size, keyset-friendly filters,
//  * agent-wise breakdown card. Every row has a per-row delete; a bulk purge
//  * button lets you drop everything older than N days at once.
//  */
// export default function MailRecords() {
//   const [page, setPage] = useState(1)
//   const [perPage] = useState(25)
//   const [direction, setDirection] = useState('')       // '' | 'in' | 'out'
//   const [agentId, setAgentId] = useState('')
//   const [q, setQ] = useState('')
//   const [debouncedQ, setDebouncedQ] = useState('')
//   const [includeSpam, setIncludeSpam] = useState(false)

//   const [data, setData] = useState({ items: [], total: 0, page: 1, per_page: 25 })
//   const [agents, setAgents] = useState([])
//   const [summary, setSummary] = useState([])
//   const [busy, setBusy] = useState(false)
//   const [opened, setOpened] = useState(null)          // row expanded
//   const [toast, show] = useToast()

//   // debounce search input so we don't spam the API on every keystroke
//   useEffect(() => {
//     const t = setTimeout(() => setDebouncedQ(q.trim()), 300)
//     return () => clearTimeout(t)
//   }, [q])

//   const load = useCallback(async () => {
//     setBusy(true)
//     const params = new URLSearchParams({ page, per_page: perPage })
//     if (direction) params.set('direction', direction)
//     if (agentId) params.set('agent_id', agentId)
//     if (debouncedQ) params.set('q', debouncedQ)
//     if (includeSpam) params.set('include_spam', 'true')
//     try {
//       const d = await api.mailRecords(params.toString())
//       setData(d)
//     } catch (e) { show(e.message, true) } finally { setBusy(false) }
//   }, [page, perPage, direction, agentId, debouncedQ, includeSpam, show])

//   useEffect(() => { load() }, [load])
//   useEffect(() => { api.agents().then(setAgents).catch(() => {}) }, [])
//   useEffect(() => { api.mailRecordsAgentSummary().then(setSummary).catch(() => {}) }, [])

//   // reset to page 1 whenever a filter changes
//   useEffect(() => { setPage(1) }, [direction, agentId, debouncedQ, includeSpam])

//   const totalPages = Math.max(1, Math.ceil((data.total || 0) / perPage))

//   const removeOne = async (id) => {
//     if (!confirm('Delete this record permanently?')) return
//     try { await api.deleteMailRecord(id); show('Deleted'); load() }
//     catch (e) { show(e.message, true) }
//   }

//   const purgeOld = async () => {
//     const days = prompt('Purge every mail record older than how many days?', '90')
//     if (!days) return
//     const n = parseInt(days, 10)
//     if (!Number.isFinite(n) || n < 1) { show('Enter a positive number', true); return }
//     if (!confirm(`Permanently delete every record older than ${n} days? This can't be undone.`)) return
//     try {
//       const r = await api.purgeMailOlderThan(n)
//       show(`Purged ${r.deleted ?? 0} records`)
//       load()
//       api.mailRecordsAgentSummary().then(setSummary).catch(() => {})
//     } catch (e) { show(e.message, true) }
//   }

//   const totalSent = useMemo(() => summary.reduce((s, a) => s + (a.sent || 0), 0), [summary])
//   const totalRecv = useMemo(() => summary.reduce((s, a) => s + (a.received || 0), 0), [summary])

//   return (
//     <>
//       <div className="records-intro card mb">
//         <div className="badge-circle blue"><IconArchive /></div>
//         <div style={{ flex: 1 }}>
//           <b>Mail Records — every email, every agent, one place</b>
//           <p className="sm mut mt">
//             Full audit trail of {' '}
//             <b><Counter value={data.total || 0} /></b> messages — inbound + outbound + spam.
//             Search by sender/subject, filter by agent or direction, delete row-by-row, or bulk-purge old
//             records. Optimized for 50 000+ rows: server-side paging, no browser slowdown.
//           </p>
//         </div>
//         <div className="row" style={{ gap: 8 }}>
//           <button className="btn ghost small" onClick={load} title="Refresh"><IconRefresh /> Refresh</button>
//           <button className="btn danger small" onClick={purgeOld}><IconTrash /> Purge old…</button>
//         </div>
//       </div>

//       {/* Agent breakdown row */}
//       <div className="records-agent-strip mb">
//         <div
//           className={`records-agent-card ${agentId === '' ? 'on' : ''}`}
//           onClick={() => setAgentId('')}
//         >
//           <div className="agent-name">All agents</div>
//           <div className="agent-stats">
//             <span><IconSend /> <Counter value={totalSent} /></span>
//             <span><IconInbox /> <Counter value={totalRecv} /></span>
//           </div>
//         </div>
//         {summary.map(a => (
//           <div key={a.agent_id ?? 'sys'}
//                className={`records-agent-card ${String(agentId) === String(a.agent_id) ? 'on' : ''}`}
//                onClick={() => setAgentId(String(a.agent_id ?? ''))}>
//             <div className="agent-name">{a.name || (a.agent_id ? `#${a.agent_id}` : 'system')}</div>
//             <div className="agent-stats">
//               <span><IconSend /> <Counter value={a.sent || 0} /></span>
//               <span><IconInbox /> <Counter value={a.received || 0} /></span>
//             </div>
//           </div>
//         ))}
//       </div>

//       {/* Filter bar */}
//       <div className="records-filter card mb">
//         <div className="filter-search">
//           <IconSearch />
//           <input placeholder="Search sender, subject, or body…" value={q} onChange={(e) => setQ(e.target.value)} />
//         </div>
//         <div className="filter-group">
//           <IconFilter />
//           <div className="seg">
//             <button className={direction === '' ? 'on' : ''} onClick={() => setDirection('')}>All</button>
//             <button className={direction === 'out' ? 'on' : ''} onClick={() => setDirection('out')}>Sent</button>
//             <button className={direction === 'in' ? 'on' : ''} onClick={() => setDirection('in')}>Received</button>
//           </div>
//           <label className="chk">
//             <input type="checkbox" checked={includeSpam} onChange={(e) => setIncludeSpam(e.target.checked)} />
//             <span>Include spam</span>
//           </label>
//         </div>
//       </div>

//       {/* Table */}
//       <div className="card records-table-card">
//         {busy && data.items.length === 0 && <div className="empty">Loading records…</div>}
//         {!busy && data.items.length === 0 && <div className="empty">No records match — try clearing filters.</div>}
//         {data.items.length > 0 && (
//           <table className="records-table">
//             <thead>
//               <tr>
//                 <th style={{ width: 44 }}></th>
//                 <th>Direction</th>
//                 <th>Agent</th>
//                 <th>Contact</th>
//                 <th>Subject</th>
//                 <th>When</th>
//                 <th style={{ width: 44 }}></th>
//               </tr>
//             </thead>
//             <tbody>
//               {data.items.map(r => (
//                 <React.Fragment key={r.id}>
//                   <tr className={`record-row ${opened === r.id ? 'open' : ''}`} onClick={() => setOpened(opened === r.id ? null : r.id)}>
//                     <td>
//                       <span className={`dir-pill ${r.direction}`}>
//                         {r.direction === 'in' ? <IconInbox /> : <IconSend />}
//                       </span>
//                     </td>
//                     <td><span className="pill ok">{r.direction === 'in' ? 'Inbound' : 'Outbound'}</span></td>
//                     <td>{r.agent_name || <span className="mut">system</span>}</td>
//                     <td>
//                       <b className="ellipsis">{r.lead_name || r.contact_email || '—'}</b>
//                       <div className="sm mut ellipsis">{r.contact_email}</div>
//                     </td>
//                     <td><span className="ellipsis">{r.subject || <span className="mut">(no subject)</span>}</span></td>
//                     <td className="sm mut">{new Date(r.created_at + 'Z').toLocaleString()}</td>
//                     <td>
//                       <button className="icon-btn danger" onClick={(e) => { e.stopPropagation(); removeOne(r.id) }} title="Delete">
//                         <IconTrash />
//                       </button>
//                     </td>
//                   </tr>
//                   {opened === r.id && (
//                     <tr className="record-detail">
//                       <td colSpan={7}>
//                         <div className="record-body">
//                           {r.body ? <pre>{r.body}</pre> : <div className="mut sm">(no body stored)</div>}
//                         </div>
//                       </td>
//                     </tr>
//                   )}
//                 </React.Fragment>
//               ))}
//             </tbody>
//           </table>
//         )}
//       </div>

//       {/* Pager */}
//       <div className="pager mt">
//         <button className="btn ghost small" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
//         <span className="sm mut">Page {data.page} of {totalPages} · {data.total} records</span>
//         <button className="btn ghost small" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next →</button>
//       </div>
//       <Toast toast={toast} />
//     </>
//   )
// }


import React, { useEffect, useMemo, useState, useCallback } from 'react'
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
 */
export default function MailRecords() {
  const [page, setPage] = useState(1)
  const [perPage] = useState(25)
  const [direction, setDirection] = useState('')       // '' | 'in' | 'out'
  const [agentId, setAgentId] = useState('')
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [includeSpam, setIncludeSpam] = useState(false)

  const [data, setData] = useState({ items: [], total: 0, page: 1, per_page: 25 })
  const [agents, setAgents] = useState([])
  const [summary, setSummary] = useState([])
  const [busy, setBusy] = useState(false)
  const [opened, setOpened] = useState(null)          // row expanded
  const [toast, show] = useToast()

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
    if (includeSpam) params.set('include_spam', 'true')
    try {
      const d = await api.mailRecords(params.toString())
      setData(d)
    } catch (e) { show(e.message, true) } finally { setBusy(false) }
  }, [page, perPage, direction, agentId, debouncedQ, includeSpam, show])

  useEffect(() => { load() }, [load])
  useEffect(() => { api.agents().then(setAgents).catch(() => {}) }, [])
  useEffect(() => { api.mailRecordsAgentSummary().then(setSummary).catch(() => {}) }, [])

  // reset to page 1 whenever a filter changes
  useEffect(() => { setPage(1) }, [direction, agentId, debouncedQ, includeSpam])

  const totalPages = Math.max(1, Math.ceil((data.total || 0) / perPage))

  const removeOne = async (id) => {
    if (!confirm('Delete this record permanently?')) return
    try { await api.deleteMailRecord(id); show('Deleted'); load() }
    catch (e) { show(e.message, true) }
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
            Search by sender/subject, filter by agent or direction, delete row-by-row, or bulk-purge old
            records. Optimized for 50 000+ rows: server-side paging, no browser slowdown.
          </p>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn ghost small" onClick={load} title="Refresh"><IconRefresh /> Refresh</button>
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
                    <td><span className="ellipsis">{r.subject || <span className="mut">(no subject)</span>}</span></td>
                    <td className="sm mut">{new Date(r.created_at + 'Z').toLocaleString()}</td>
                    <td>
                      <button className="icon-btn danger" onClick={(e) => { e.stopPropagation(); removeOne(r.id) }} title="Delete">
                        <IconTrash />
                      </button>
                    </td>
                  </tr>
                  {opened === r.id && (
                    <tr className="record-detail">
                      <td colSpan={7}>
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