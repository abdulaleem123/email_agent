// import React, { useEffect, useRef, useState, useCallback } from 'react'
// import { api } from '../api.js'
// import MiniOrb from '../MiniOrb.jsx'
// import { Toast, useToast } from '../App.jsx'
// import Counter from '../Counter.jsx'
// import { IconUsers, IconPlus, IconTrash, IconRefresh, IconSearch, IconRocket } from '../Icons.jsx'

// /**
//  * Leads — the queue of people your agents will reach out to.
//  *
//  * Non-technical explainer at the top. Paginated (25/page, server-side) so
//  * 50 000-row sheets don't freeze the browser. Bulk delete + auto-purge for
//  * completed leads keeps the DB slim. Agent assignment happens at enrollment.
//  */
// export default function Leads() {
//   const [data, setData] = useState({ items: [], total: 0, page: 1, per_page: 25 })
//   const [stats, setStats] = useState(null)
//   const [page, setPage] = useState(1)
//   const perPage = 25
//   const [status, setStatus] = useState('')
//   const [unverifiedOnly, setUnverifiedOnly] = useState(false)
//   const [unassignedOnly, setUnassignedOnly] = useState(false)
//   const [q, setQ] = useState('')
//   const [debouncedQ, setDebouncedQ] = useState('')
//   const [campaigns, setCampaigns] = useState([])
//   const [agents, setAgents] = useState([])
//   const [sel, setSel] = useState(new Set())
//   const [rowAgentSel, setRowAgentSel] = useState({})   // leadId -> chosen agent_id in the row dropdown
//   const [campaignId, setCampaignId] = useState('')
//   const [agentId, setAgentId] = useState('')
//   const [busy, setBusy] = useState(false)
//   const [verifying, setVerifying] = useState(false)
//   const [showHow, setShowHow] = useState(false)
//   const fileRef = useRef()
//   const [toast, show] = useToast()

//   useEffect(() => {
//     const t = setTimeout(() => setDebouncedQ(q.trim()), 300)
//     return () => clearTimeout(t)
//   }, [q])
//   useEffect(() => { setPage(1) }, [status, debouncedQ, unverifiedOnly, unassignedOnly, agentId])

//   const load = useCallback(async () => {
//     const params = new URLSearchParams({ page, per_page: perPage })
//     if (status) params.set('status', status)
//     if (debouncedQ) params.set('q', debouncedQ)
//     if (unverifiedOnly) params.set('unverified_only', 'true')
//     if (unassignedOnly) params.set('unassigned_only', 'true')
//     if (agentId) params.set('agent_id', agentId)
//     try {
//       const [d, s, cs, ag] = await Promise.all([
//         api.leadsPaged(params.toString()),
//         api.leadsStats(),
//         api.campaigns(),
//         api.agents(),
//       ])
//       setData(d); setStats(s); setCampaigns(cs); setAgents(ag)
//       if (cs.length && !campaignId) setCampaignId(String(cs[0].id))
//     } catch (e) { show(e.message, true) }
//   }, [page, status, debouncedQ, campaignId, agentId, unassignedOnly, unverifiedOnly, show])

//   useEffect(() => { load() }, [load])

//   const upload = async (e) => {
//     const file = e.target.files[0]
//     if (!file) return
//     setBusy(true)
//     try {
//       // If an agent + campaign are picked in the toolbar, leads land already
//       // enrolled with that agent — no one-by-one assigning.
//       const r = await api.uploadLeads(file, agentId || undefined, campaignId || undefined)
//       const where = r.assigned_to_agent
//         ? ` · auto-assigned to ${agents.find(a => a.id === +agentId)?.name || 'agent'}`
//         : ''
//       show(`Imported ${r.created} leads · ${r.skipped_duplicates} dup skipped${where}`)
//       load()
//     } catch (ex) { show(ex.message, true) } finally { setBusy(false); e.target.value = '' }
//   }

//   const verifyMailboxes = async () => {
//     setVerifying(true); setBusy(true)
//     try { const r = await api.verifyMailboxes(); show(`Checked ${r.checked}: ${r.confirmed} confirmed, ${r.still_unverified} unverified`); load() }
//     catch (ex) { show(ex.message, true) } finally { setVerifying(false); setBusy(false) }
//   }

//   const bulkGarbage = async () => {
//     if (!sel.size) return
//     setBusy(true)
//     try { const r = await api.bulkGarbageLeads([...sel]); show(`Moved ${r.moved} lead(s) → Garbage`); setSel(new Set()); load() }
//     catch (ex) { show(ex.message, true) } finally { setBusy(false) }
//   }

//   const moveUnverifiedToGarbage = async () => {
//     if (!confirm('Move ALL unverified leads to Garbage? They are not deleted — you can review or restore them in Garbage.')) return
//     setBusy(true)
//     try { const r = await api.unverifiedToGarbage(); show(`Moved ${r.moved} unverified lead(s) to Garbage`); load() }
//     catch (ex) { show(ex.message, true) } finally { setBusy(false) }
//   }

//   const deleteAll = async () => {
//     if (!confirm('Delete ALL leads and their messages? This wipes the whole sheet.')) return
//     setBusy(true)
//     try { const r = await api.deleteAllLeads(); show(`Deleted ${r.deleted} leads`); load() }
//     catch (ex) { show(ex.message, true) } finally { setBusy(false) }
//   }

//   const [purgeDays, setPurgeDays] = useState(null)   // null = modal closed, else the typed value

//   const runPurge = async () => {
//     const n = parseInt(purgeDays, 10)
//     if (!Number.isFinite(n) || n < 1) { show('Enter a positive number', true); return }
//     try { const r = await api.purgeCompletedLeads(n); show(`Purged ${r.deleted} leads`); load() }
//     catch (ex) { show(ex.message, true) } finally { setPurgeDays(null) }
//   }

//   const launchable = data.items.filter(l => ['new', 'enrolled'].includes(l.status))
//   const toggleAll = () => setSel(s => s.size === launchable.length ? new Set() : new Set(launchable.map(l => l.id)))
//   const toggleOne = (id) => setSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })

//   const [blockedInfo, setBlockedInfo] = useState(null)

//   const enrollOneWithAgent = async (lead, chosenAgentId) => {
//     if (!chosenAgentId || !campaignId) { show('Pick a campaign in the toolbar above first', true); return }
//     try {
//       const r = await api.enroll([lead.id], +campaignId, +chosenAgentId)
//       if (r.blocked?.length) { setBlockedInfo(r.blocked); return }
//       const rl = await api.launch(+campaignId, [lead.id])
//       show(`${lead.name || lead.email} enrolled with ${agents.find(a => a.id === +chosenAgentId)?.name || 'agent'} — queued`)
//       load()
//     } catch (ex) { show(ex.message, true) }
//   }

//   const enrollAndLaunch = async () => {
//     if (!sel.size || !campaignId) return
//     setBusy(true)
//     try {
//       const ids = [...sel]
//       const r = await api.enroll(ids, +campaignId, agentId ? +agentId : undefined)
//       if (r.blocked?.length) {
//         setBlockedInfo(r.blocked)
//       }
//       const blockedIds = new Set((r.blocked || []).map(b => b.lead_id))
//       const goIds = ids.filter(id => !blockedIds.has(id))
//       if (goIds.length) {
//         const rl = await api.launch(+campaignId, goIds)
//         show(`Queued ${rl.queued} emails in ${rl.batches?.length || 0} batch(es) of ~${rl.batch_size}`)
//       } else if (!r.blocked?.length) {
//         show('Nothing to enroll', true)
//       }
//       setSel(new Set()); load()
//     } catch (ex) { show(ex.message, true) } finally { setBusy(false) }
//   }

//   // SELECT-ALL-MATCHING: enroll every lead in the current filter (all pages),
//   // without shipping thousands of IDs. Great for 20k–50k sheets and for
//   // "assign all unassigned leads to <agent>".
//   const enrollAllMatching = async () => {
//     if (!campaignId) { show('Pick a campaign first', true); return }
//     const who = agentId ? (agents.find(a => a.id === +agentId)?.name || 'agent') : null
//     const target = who || (campaigns.find(c => c.id === +campaignId)?.name && 'the campaign\u2019s default agent')
//     if (!agentId) { show('Pick an agent in the toolbar to enroll all matching', true); return }
//     if (!confirm(`Enroll ALL ${data.total} matching lead(s) into this campaign with ${who}? They queue in batches automatically.`)) return
//     setBusy(true)
//     try {
//       const r = await api.enrollByFilter({
//         campaign_id: +campaignId,
//         agent_id: +agentId,
//         status: status || undefined,
//         // when filtering to unassigned leads, don't also restrict by a current
//         // agent (they'd contradict) — we're assigning them FOR THE FIRST TIME
//         filter_agent_id: (!unassignedOnly && agentId) ? +agentId : undefined,
//         unverified_only: unverifiedOnly,
//         unassigned_only: unassignedOnly,
//         q: debouncedQ || '',
//       })
//       show(`Enrolled ${r.enrolled} · queued in ${r.batches?.length || 0} batch(es) of ~${r.batch_size}` +
//            (r.blocked_count ? ` · ${r.blocked_count} skipped (24h lock)` : ''))
//       setSel(new Set()); load()
//     } catch (ex) { show(ex.message, true) } finally { setBusy(false) }
//   }

//   const research = async (l) => {
//     show(`Researching ${l.company || l.email}…`)
//     try { await api.research(l.id); load(); show('Research + pain points saved') }
//     catch (ex) { show(ex.message, true) }
//   }

//   const bulkDelete = async () => {
//     if (!sel.size) return
//     if (!confirm(`Delete ${sel.size} selected leads?`)) return
//     try { await api.bulkDeleteLeads([...sel]); setSel(new Set()); load(); show('Deleted') }
//     catch (ex) { show(ex.message, true) }
//   }

//   const totalPages = Math.max(1, Math.ceil((data.total || 0) / perPage))

//   return (
//     <>
//       <div className="records-intro card mb">
//         <MiniOrb size={52} color="#0054FC" accent="#00BAFF" />
//         <div style={{ flex: 1 }}>
//           <b>Leads — your outreach queue</b>
//           <p className="sm mut mt">
//             <b><Counter value={stats?.total || 0} /></b> total leads · {stats?.contacted || 0} contacted ·
//             &nbsp;{stats?.replied || 0} replied · {stats?.garbage || 0} in garbage.
//             Server-side paging handles 50 000+ rows without slowdown.
//           </p>
//         </div>
//         <button className="btn ghost small" onClick={() => setShowHow(s => !s)}>
//           {showHow ? 'Hide' : 'How this works'} →
//         </button>
//       </div>

//       {purgeDays !== null && (
//         <div className="modal-veil" onClick={e => e.target === e.currentTarget && setPurgeDays(null)}>
//           <div className="card">
//             <b>Purge old completed / garbage leads</b>
//             <p className="sm mut mt">
//               Permanently deletes leads whose status is <b>completed</b> or <b>garbage</b> and haven't
//               been touched in this many days — keeps the database lean at 50 000+ scale. Active,
//               enrolled, or recently-replied leads are never touched by this.
//             </p>
//             <div className="field mt">
//               <label>Older than (days)</label>
//               <input type="number" min={1} value={purgeDays} onChange={e => setPurgeDays(e.target.value)} autoFocus />
//             </div>
//             <div className="row mt">
//               <button className="btn danger" onClick={runPurge}>Purge now</button>
//               <button className="btn ghost" onClick={() => setPurgeDays(null)}>Cancel</button>
//             </div>
//           </div>
//         </div>
//       )}

//       {blockedInfo && (
//         <div className="modal-veil" onClick={e => e.target === e.currentTarget && setBlockedInfo(null)}>
//           <div className="card">
//             <b style={{ color: 'var(--hot)' }}>⚠ {blockedInfo.length} lead(s) already claimed today</b>
//             <p className="sm mut mt">
//               Another agent already emailed these leads today — the same-day lock means
//               only they can send to these leads until it resets tomorrow.
//             </p>
//             <div className="mt" style={{ maxHeight: 240, overflowY: 'auto' }}>
//               {blockedInfo.map(b => (
//                 <div key={b.lead_id} className="row between sm" style={{ padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
//                   <span>{b.email}</span>
//                   <span className="mut">
//                     owned by <b>{b.owned_by}</b> · unlocks {new Date(b.unlock_at + 'Z').toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
//                   </span>
//                 </div>
//               ))}
//             </div>
//             <button className="btn mt" onClick={() => setBlockedInfo(null)}>Got it</button>
//           </div>
//         </div>
//       )}

//       {showHow && (
//         <div className="card mb explainer">
//           <h3>How leads flow through the system</h3>
//           <ol>
//             <li><b>Upload</b> — drop an Excel or CSV. Any column layout works (company / name / email / website / country auto-detected). Duplicates are skipped, invalid mailboxes flagged red.</li>
//             <li><b>Verify</b> — click "Verify mailboxes (SMTP)" to check which addresses actually exist before you send.</li>
//             <li><b>Select</b> — tick the leads you want to reach out to. Filter by status or search by name/email.</li>
//             <li><b>Pick a campaign & agent</b> — the agent decides tone, mailbox, signature, and reply style. Leave "Any agent" for round-robin.</li>
//             <li><b>Enroll & launch</b> — leads split into batches of ~20-50. Each batch spaces emails 1-5 min apart.</li>
//             <li><b>24-hour agent lock</b> — once an agent actually emails a lead, no other agent can enroll or email that same lead for 24 hours. The Agent column shows 🔒 with the exact unlock time; the per-row agent dropdown only offers the owning agent while it's locked. After 24 hours it opens up to any agent again.</li>
//             <li><b>Filter by agent</b> — the "Any agent" dropdown above both filters the list to that agent's leads AND sets who gets used for bulk Enroll &amp; launch.</li>
//             <li><b>Watch replies</b> — inbound answers land in <b>Messages</b>. The agent auto-replies ~15 min later, KB-first. You can take over anytime.</li>
//             <li><b>Housekeeping</b> — delete leads one-by-one, in bulk, or purge everything older than X days. Old completed leads never bog the DB down.</li>
//           </ol>
//         </div>
//       )}

//       {/* Toolbar */}
//       <div className="row between mb wrap" style={{ gap: 10 }}>
//         <div className="row" style={{ gap: 8 }}>
//           <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv" onChange={upload} style={{ display: 'none' }} />
//           <button className="btn" disabled={busy} onClick={() => fileRef.current.click()}>
//             <IconPlus /> {busy && !verifying ? 'Uploading…' : 'Upload Excel / CSV'}
//           </button>
//           <button className="btn ghost small" disabled={busy || data.items.length === 0} onClick={verifyMailboxes}>
//             {verifying ? 'Verifying (DNS + SMTP)… please wait' : 'Verify mailboxes'}
//           </button>
//           <button className="btn ghost small" disabled={busy} onClick={moveUnverifiedToGarbage}
//                   title="Move every unverified lead into Garbage (reviewable, not deleted)">
//             Unverified → Garbage
//           </button>
//           <button className="btn ghost small" disabled={busy} onClick={() => setPurgeDays('60')}>
//             Purge old…
//           </button>
//           <button className="btn danger small" disabled={busy || (data.total || 0) === 0} onClick={deleteAll}>
//             <IconTrash /> Delete all
//           </button>
//         </div>
//         <div className="row" style={{ gap: 8 }}>
//           <select style={{ width: 160 }} value={agentId} onChange={e => setAgentId(e.target.value)}>
//             <option value="">Any agent</option>
//             {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
//           </select>
//           <select style={{ width: 200 }} value={campaignId} onChange={e => setCampaignId(e.target.value)}>
//             {campaigns.length === 0 && <option value="">No campaigns</option>}
//             {campaigns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
//           </select>
//           <button className="btn" disabled={!sel.size || !campaignId || busy} onClick={enrollAndLaunch}>
//             <IconRocket /> Enroll &amp; launch {sel.size ? `(${sel.size})` : ''}
//           </button>
//           <button className="btn ghost" disabled={!campaignId || !agentId || busy || (data.total || 0) === 0}
//                   onClick={enrollAllMatching}
//                   title="Enroll EVERY lead matching the current filter (all pages), not just this page">
//             <IconRocket /> Enroll all {data.total || 0} matching
//           </button>
//         </div>
//       </div>

//       {/* Filter bar */}
//       <div className="records-filter card mb">
//         <div className="filter-search">
//           <IconSearch />
//           <input placeholder="Search name, email or company…" value={q} onChange={e => setQ(e.target.value)} />
//         </div>
//         <div className="filter-group">
//           <div className="seg">
//             {['', 'new', 'enrolled', 'contacted', 'replied', 'garbage'].map(s => (
//               <button key={s || 'all'} className={status === s ? 'on' : ''} onClick={() => setStatus(s)}>
//                 {s || 'All'}
//               </button>
//             ))}
//           </div>
//           <button className={`btn small ${unverifiedOnly ? '' : 'ghost'}`}
//                   style={unverifiedOnly ? { background: 'var(--hot)' } : undefined}
//                   onClick={() => setUnverifiedOnly(v => !v)}
//                   title="Show only suspicious/unverified emails">
//             ⚠ Suspicious (unverified) only
//           </button>
//           <button className={`btn small ${unassignedOnly ? '' : 'ghost'}`}
//                   style={unassignedOnly ? { background: 'var(--brand, #0054FC)', color: '#fff' } : undefined}
//                   onClick={() => setUnassignedOnly(v => !v)}
//                   title="Show only leads not yet assigned to any agent — then 'Enroll all matching' to assign them all at once">
//             Unassigned only
//           </button>
//           {sel.size > 0 && (
//             <button className="btn small" onClick={bulkGarbage} disabled={busy}
//                     title="Move the selected leads straight to Garbage">
//               Move {sel.size} → Garbage
//             </button>
//           )}
//           {sel.size > 0 && (
//             <button className="btn danger small" onClick={bulkDelete}>
//               Delete {sel.size} selected
//             </button>
//           )}
//         </div>
//       </div>

//       <div className="card" style={{ padding: 0, overflow: 'auto' }}>
//         {data.items.length === 0
//           ? <div className="empty">No leads match — upload a sheet or clear filters.</div>
//           : (
//             <table>
//               <thead>
//                 <tr>
//                   <th style={{ width: 34 }}>
//                     <input type="checkbox" style={{ width: 16 }}
//                            checked={launchable.length > 0 && sel.size === launchable.length}
//                            onChange={toggleAll} />
//                   </th>
//                   <th>Person</th><th>Company</th><th>Country</th><th>Agent</th>
//                   <th>Status</th><th>Temp</th><th>Research</th><th></th>
//                 </tr>
//               </thead>
//               <tbody>
//                 {data.items.map(l => (
//                   <tr key={l.id} style={l.email_verified === false ? { background: '#fef2f2' } : undefined}>
//                     <td>{['new', 'enrolled'].includes(l.status)
//                       ? <input type="checkbox" style={{ width: 16 }} checked={sel.has(l.id)} onChange={() => toggleOne(l.id)} />
//                       : null}</td>
//                     <td>
//                       <b>{l.name || '—'}</b>
//                       {l.email_verified === false && <span className="pill" style={{ background: '#fee2e2', color: '#b91c1c', marginLeft: 6 }}>unverified</span>}
//                       <div className="sm mut">{l.email}</div>
//                     </td>
//                     <td>{l.company || '—'}<div className="sm mut ellipsis">{l.website}</div></td>
//                     <td>{l.country || '—'}</td>
//                     <td>
//                       {l.agent_name
//                         ? <div className="sm">{l.status === 'enrolled'
//                             ? <span>✅ enrolled with <b>{l.agent_name}</b></span>
//                             : <span><b>{l.agent_name}</b> currently</span>}</div>
//                         : <span className="mut sm">unassigned</span>}
//                       {l.locked_until && (
//                         <div className="sm mut" title="Another agent already emailed this lead today — it unlocks then">
//                           🔒 next available {new Date(l.locked_until + 'Z').toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
//                         </div>
//                       )}
//                       {['new', 'enrolled'].includes(l.status) && (
//                         <div className="row" style={{ gap: 4, marginTop: 4 }}>
//                           <select style={{ width: 110, padding: '4px 6px', fontSize: 12 }}
//                                   value={rowAgentSel[l.id] ?? ''}
//                                   onChange={e => setRowAgentSel(s => ({ ...s, [l.id]: e.target.value }))}>
//                             <option value="">Pick agent…</option>
//                             {agents
//                               .filter(a => !l.locked_until || a.name === l.agent_name)
//                               .map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
//                           </select>
//                           <button className="btn ghost small" disabled={!rowAgentSel[l.id]}
//                                   onClick={() => enrollOneWithAgent(l, rowAgentSel[l.id])}>
//                             Enroll
//                           </button>
//                         </div>
//                       )}
//                     </td>
//                     <td><span className={`pill ${l.status === 'replied' ? 'ok' : l.status === 'contacted' ? 'blue' : 'gray'}`}>{l.status}</span></td>
//                     <td><span className={`pill ${l.temperature}`}>{l.temperature}</span></td>
//                     <td className="sm mut" style={{ maxWidth: 260 }}>
//                       {l.pain_points ? l.pain_points.slice(0, 100) + '…' : <i>none yet</i>}
//                     </td>
//                     <td>
//                       <div className="row" style={{ gap: 4 }}>
//                         <button className="btn ghost small" onClick={() => research(l)}>Research</button>
//                         <button className="icon-btn danger" onClick={async () => { await api.deleteLead(l.id); load() }}><IconTrash /></button>
//                       </div>
//                     </td>
//                   </tr>
//                 ))}
//               </tbody>
//             </table>
//           )}
//       </div>

//       <div className="pager mt">
//         <button className="btn ghost small" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
//         <span className="sm mut">Page {data.page} of {totalPages} · {data.total} leads</span>
//         <button className="btn ghost small" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next →</button>
//       </div>
//       <Toast toast={toast} />
//     </>
//   )
// }

import React, { useEffect, useRef, useState, useCallback } from 'react'
import { api } from '../api.js'
import MiniOrb from '../MiniOrb.jsx'
import { Toast, useToast } from '../App.jsx'
import Counter from '../Counter.jsx'
import { IconUsers, IconPlus, IconTrash, IconRefresh, IconSearch, IconRocket } from '../Icons.jsx'
 
/**
 * Leads — the queue of people your agents will reach out to.
 *
 * Non-technical explainer at the top. Paginated (25/page, server-side) so
 * 50 000-row sheets don't freeze the browser. Bulk delete + auto-purge for
 * completed leads keeps the DB slim. Agent assignment happens at enrollment.
 */
export default function Leads() {
  const [data, setData] = useState({ items: [], total: 0, page: 1, per_page: 25 })
  const [stats, setStats] = useState(null)
  const [page, setPage] = useState(1)
  const perPage = 25
  const [status, setStatus] = useState('')
  const [unverifiedOnly, setUnverifiedOnly] = useState(false)
  const [unassignedOnly, setUnassignedOnly] = useState(false)
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
  const fileRef = useRef()
  const [toast, show] = useToast()
 
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 300)
    return () => clearTimeout(t)
  }, [q])
  useEffect(() => { setPage(1) }, [status, debouncedQ, unverifiedOnly, unassignedOnly, agentId])
 
  const load = useCallback(async () => {
    const params = new URLSearchParams({ page, per_page: perPage })
    if (status) params.set('status', status)
    if (debouncedQ) params.set('q', debouncedQ)
    if (unverifiedOnly) params.set('unverified_only', 'true')
    if (unassignedOnly) params.set('unassigned_only', 'true')
    if (agentId) params.set('agent_id', agentId)
    try {
      const [d, s, cs, ag] = await Promise.all([
        api.leadsPaged(params.toString()),
        api.leadsStats(),
        api.campaigns(),
        api.agents(),
      ])
      setData(d); setStats(s); setCampaigns(cs); setAgents(ag)
      if (cs.length && !campaignId) setCampaignId(String(cs[0].id))
    } catch (e) { show(e.message, true) }
  }, [page, status, debouncedQ, campaignId, agentId, unassignedOnly, unverifiedOnly, show])
 
  useEffect(() => { load() }, [load])
 
  const upload = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    setBusy(true)
    try {
      // If an agent + campaign are picked in the toolbar, leads land already
      // enrolled with that agent — no one-by-one assigning.
      const r = await api.uploadLeads(file, agentId || undefined, campaignId || undefined)
      const where = r.assigned_to_agent
        ? ` · auto-assigned to ${agents.find(a => a.id === +agentId)?.name || 'agent'}`
        : ''
      show(`Imported ${r.created} leads · ${r.skipped_duplicates} dup skipped${where}`)
      load()
    } catch (ex) { show(ex.message, true) } finally { setBusy(false); e.target.value = '' }
  }
 
  const verifyMailboxes = async () => {
    setVerifying(true); setBusy(true)
    try { const r = await api.verifyMailboxes(); show(`Checked ${r.checked}: ${r.confirmed} confirmed, ${r.still_unverified} unverified`); load() }
    catch (ex) { show(ex.message, true) } finally { setVerifying(false); setBusy(false) }
  }
 
  const bulkGarbage = async () => {
    if (!sel.size) return
    setBusy(true)
    try { const r = await api.bulkGarbageLeads([...sel]); show(`Moved ${r.moved} lead(s) → Garbage`); setSel(new Set()); load() }
    catch (ex) { show(ex.message, true) } finally { setBusy(false) }
  }
 
  // BULK ASSIGN: pick ONE agent, apply to every selected lead at once (assign +
  // enroll + launch) — no more per-row 'Pick agent' one-by-one.
  const enrollSelectedWith = async () => {
    if (!campaignId) { show('Pick a campaign first', true); return }
    if (!bulkAgent) { show('Choose an agent to assign', true); return }
    const ids = [...sel].filter(id => launchable.some(l => l.id === id))
    if (!ids.length) { show('None of the selected leads are enrollable (new/enrolled only)', true); return }
    const who = agents.find(a => a.id === +bulkAgent)?.name || 'agent'
    setBusy(true)
    try {
      await api.enroll(ids, +campaignId, +bulkAgent)
      await api.launch(+campaignId, ids)
      show(`${ids.length} lead(s) assigned to ${who} & queued`)
      setSel(new Set()); load()
    } catch (ex) { show(ex.message, true) } finally { setBusy(false) }
  }
 
  const moveUnverifiedToGarbage = async () => {
    if (!confirm('Move ALL unverified leads to Garbage? They are not deleted — you can review or restore them in Garbage.')) return
    setBusy(true)
    try { const r = await api.unverifiedToGarbage(); show(`Moved ${r.moved} unverified lead(s) to Garbage`); load() }
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
      const r = await api.enroll([lead.id], +campaignId, +chosenAgentId)
      if (r.blocked?.length) { setBlockedInfo(r.blocked); return }
      const rl = await api.launch(+campaignId, [lead.id])
      show(`${lead.name || lead.email} enrolled with ${agents.find(a => a.id === +chosenAgentId)?.name || 'agent'} — queued`)
      load()
    } catch (ex) { show(ex.message, true) }
  }
 
  const enrollAndLaunch = async () => {
    if (!sel.size || !campaignId) return
    setBusy(true)
    try {
      const ids = [...sel]
      const r = await api.enroll(ids, +campaignId, agentId ? +agentId : undefined)
      if (r.blocked?.length) {
        setBlockedInfo(r.blocked)
      }
      const blockedIds = new Set((r.blocked || []).map(b => b.lead_id))
      const goIds = ids.filter(id => !blockedIds.has(id))
      if (goIds.length) {
        const rl = await api.launch(+campaignId, goIds)
        show(`Queued ${rl.queued} emails in ${rl.batches?.length || 0} batch(es) of ~${rl.batch_size}`)
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
      const r = await api.enrollByFilter({
        campaign_id: +campaignId,
        agent_id: +agentId,
        status: status || undefined,
        // when filtering to unassigned leads, don't also restrict by a current
        // agent (they'd contradict) — we're assigning them FOR THE FIRST TIME
        filter_agent_id: (!unassignedOnly && agentId) ? +agentId : undefined,
        unverified_only: unverifiedOnly,
        unassigned_only: unassignedOnly,
        q: debouncedQ || '',
      })
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
            <b style={{ color: 'var(--hot)' }}>⚠ {blockedInfo.length} lead(s) already claimed today</b>
            <p className="sm mut mt">
              Another agent already emailed these leads today — the same-day lock means
              only they can send to these leads until it resets tomorrow.
            </p>
            <div className="mt" style={{ maxHeight: 240, overflowY: 'auto' }}>
              {blockedInfo.map(b => (
                <div key={b.lead_id} className="row between sm" style={{ padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
                  <span>{b.email}</span>
                  <span className="mut">
                    owned by <b>{b.owned_by}</b> · unlocks {new Date(b.unlock_at + 'Z').toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
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
            <li><b>Enroll & launch</b> — leads split into batches of ~20-50. Each batch spaces emails 1-5 min apart.</li>
            <li><b>24-hour agent lock</b> — once an agent actually emails a lead, no other agent can enroll or email that same lead for 24 hours. The Agent column shows 🔒 with the exact unlock time; the per-row agent dropdown only offers the owning agent while it's locked. After 24 hours it opens up to any agent again.</li>
            <li><b>Filter by agent</b> — the "Any agent" dropdown above both filters the list to that agent's leads AND sets who gets used for bulk Enroll &amp; launch.</li>
            <li><b>Watch replies</b> — inbound answers land in <b>Messages</b>. The agent auto-replies ~15 min later, KB-first. You can take over anytime.</li>
            <li><b>Housekeeping</b> — delete leads one-by-one, in bulk, or purge everything older than X days. Old completed leads never bog the DB down.</li>
          </ol>
        </div>
      )}
 
      {/* Toolbar */}
      <div className="row between mb wrap" style={{ gap: 10 }}>
        <div className="row" style={{ gap: 8 }}>
          <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv" onChange={upload} style={{ display: 'none' }} />
          <button className="btn" disabled={busy} onClick={() => fileRef.current.click()}>
            <IconPlus /> {busy && !verifying ? 'Uploading…' : 'Upload Excel / CSV'}
          </button>
          <button className="btn ghost small" disabled={busy || data.items.length === 0} onClick={verifyMailboxes}>
            {verifying ? 'Verifying (DNS + SMTP)… please wait' : 'Verify mailboxes'}
          </button>
          <button className="btn ghost small" disabled={busy} onClick={moveUnverifiedToGarbage}
                  title="Move every unverified lead into Garbage (reviewable, not deleted)">
            Unverified → Garbage
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
          <button className="btn" disabled={!sel.size || !campaignId || busy} onClick={enrollAndLaunch}>
            <IconRocket /> Enroll &amp; launch {sel.size ? `(${sel.size})` : ''}
          </button>
          <button className="btn ghost" disabled={!campaignId || !agentId || busy || (data.total || 0) === 0}
                  onClick={enrollAllMatching}
                  title="Enroll EVERY lead matching the current filter (all pages), not just this page">
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
          {sel.size > 0 && (
            <div className="row" style={{ gap: 6, alignItems: 'center' }}>
              <select value={bulkAgent} onChange={e => setBulkAgent(e.target.value)}
                      style={{ width: 130 }} title="Assign all selected leads to this agent at once">
                <option value="">Assign agent…</option>
                {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
              <button className="btn small" disabled={!bulkAgent || !campaignId || busy}
                      onClick={enrollSelectedWith}>
                Enroll {sel.size} with agent
              </button>
            </div>
          )}
          {sel.size > 0 && (
            <button className="btn small" onClick={bulkGarbage} disabled={busy}
                    title="Move the selected leads straight to Garbage">
              Move {sel.size} → Garbage
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
                  <th>Person</th><th>Company</th><th>Country</th><th>Agent</th>
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
                      {l.email_verified === false && <span className="pill" style={{ background: '#fee2e2', color: '#b91c1c', marginLeft: 6 }}>unverified</span>}
                      <div className="sm mut">{l.email}</div>
                    </td>
                    <td>{l.company || '—'}<div className="sm mut ellipsis">{l.website}</div></td>
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
                      {['new', 'enrolled'].includes(l.status) && (
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
                    <td><span className={`pill ${l.status === 'replied' ? 'ok' : l.status === 'contacted' ? 'blue' : 'gray'}`}>{l.status}</span></td>
                    <td><span className={`pill ${l.temperature}`}>{l.temperature}</span></td>
                    <td className="sm mut" style={{ maxWidth: 260 }}>
                      {l.pain_points ? l.pain_points.slice(0, 100) + '…' : <i>none yet</i>}
                    </td>
                    <td>
                      <div className="row" style={{ gap: 4 }}>
                        <button className="btn ghost small" onClick={() => research(l)}>Research</button>
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
