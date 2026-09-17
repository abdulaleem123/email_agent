import React, { useEffect, useState, useCallback, useRef } from 'react'
import { api } from '../api.js'
import MiniOrb from '../MiniOrb.jsx'
import { Toast, useToast, useOpenAIKey } from '../App.jsx'
import { IconMic, IconUsers, IconRocket, IconArchive, IconTrash } from '../Icons.jsx'

export default function Pitch() {
  const { openaiReady } = useOpenAIKey()
  const aiDisabled = openaiReady === false
  const [leads, setLeads] = useState([])
  const [agents, setAgents] = useState([])
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(null)
  const [pitch, setPitch] = useState(null)
  const [history, setHistory] = useState([])
  const [busy, setBusy] = useState(false)
  const [ask, setAsk] = useState('')
  const [asking, setAsking] = useState(false)
  const [qa, setQa] = useState([])
  const [toast, show] = useToast()
  const threadRef = useRef(null)
  const panelBodyRef = useRef(null)

  const [showAll, setShowAll] = useState(false)
  const [records, setRecords] = useState({ items: [], total: 0, page: 1, pages: 1 })
  const [recPage, setRecPage] = useState(1)
  const [recSel, setRecSel] = useState(new Set())
  const [recOpen, setRecOpen] = useState(null)
  const [leadPage, setLeadPage] = useState(1)
  const [leadPages, setLeadPages] = useState(1)
  const [leadTotal, setLeadTotal] = useState(0)
  const [leadsLoading, setLeadsLoading] = useState(false)
   const [leadSel, setLeadSel] = useState(new Set())
  const loadRecords = useCallback(() => {
    api.pitchRecords(`page=${recPage}&per_page=20`).then(setRecords).catch(e => show(e.message, true))
  }, [recPage, show])
  useEffect(() => { if (showAll) loadRecords() }, [showAll, loadRecords])
  useEffect(() => {
    if (!showAll) return
    const t = setInterval(loadRecords, 15000)
    return () => clearInterval(t)
  }, [showAll, loadRecords])

  const toggleRecSel = (id) => setRecSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const toggleRecAll = () => setRecSel(s => s.size === records.items.length ? new Set() : new Set(records.items.map(r => r.id)))
  const bulkDeleteRecords = async () => {
    if (!recSel.size) return
    if (!confirm(`Delete ${recSel.size} pitch record(s)?`)) return
    try { await api.bulkDeletePitches([...recSel]); setRecSel(new Set()); loadRecords(); show('Deleted') }
    catch (e) { show(e.message, true) }
  }
  const deleteOneRecord = async (id) => {
    if (!confirm('Delete this pitch record?')) return
    try { await api.deletePitch(id); loadRecords(); show('Deleted') }
    catch (e) { show(e.message, true) }
  }

  const loadLeads = useCallback(() => {
    setLeadsLoading(true)
    const params = `page=${leadPage}&per_page=40&pitch_pending=true&q=${encodeURIComponent(query || '')}`
    api.leadsPaged(params)
      .then(r => {
        setLeads(r.items || [])
        setLeadPages(r.pages || 1)
        setLeadTotal(r.total || 0)
      })
      .catch(e => show(e.message, true))
      .finally(() => setLeadsLoading(false))
  }, [leadPage, query, show])

  useEffect(() => { loadLeads() }, [loadLeads])
  useEffect(() => { setLeadPage(1) }, [query])

  useEffect(() => {
    api.agents().then(setAgents).catch(() => {})
  }, [])

  const [callNotes, setCallNotes] = useState('')
  const [callBusy, setCallBusy] = useState(false)

  const osaja = agents.find(a => a.name.toLowerCase() === 'osaja')

  // Auto-scroll when new pitch arrives so full transcript is visible
  useEffect(() => {
    if (!pitch || busy || callBusy) return
    const t = setTimeout(() => {
      if (panelBodyRef.current) panelBodyRef.current.scrollTop = 0
      if (threadRef.current) threadRef.current.scrollTop = 0
    }, 80)
    return () => clearTimeout(t)
  }, [pitch?.id, busy, callBusy])

    const select = async (lead) => {
    setOpen(lead); setPitch(null); setHistory([]); setQa([]); setCallNotes('')
    const list = await api.pitches({ lead_id: lead.id }).catch(() => [])
    setHistory(Array.isArray(list) ? list : [])
    if (Array.isArray(list) && list.length) setPitch(list[0])
  }

  const generate = async () => {
    if (!open) return
    setBusy(true); setPitch(null)
    show('Building pitch from live DuckDuckGo research…')
    try {
      const rec = await api.generatePitch(open.id, osaja?.id)
      setPitch(rec); setHistory(h => [rec, ...h])
      show('Pitch ready — scroll to read full transcript')
    } catch (e) { show(e.message, true) } finally { setBusy(false) }
  }

  const generateFromCall = async () => {
    if (!open || !callNotes.trim()) return
    setCallBusy(true)
    show('Building transcript from your call notes…')
    try {
      const rec = await api.generatePickupTranscript(open.id, osaja?.id, callNotes.trim())
      setPitch(rec); setHistory(h => [rec, ...h])
      show('Call transcript ready — scroll to read full transcript')
      setCallNotes('')
    } catch (e) { show(e.message, true) } finally { setCallBusy(false) }
  }

  const removePitch = async (id) => {
    await api.deletePitch(id)
    setHistory(h => h.filter(p => p.id !== id))
    if (pitch?.id === id) setPitch(null)
    show('Pitch deleted')
  }

  const askQuestion = async () => {
    if (!open || !ask.trim()) return
    setAsking(true)
    const q = ask.trim(); setAsk('')
    try {
      const r = await api.askPitch(open.id, osaja?.id, q)
      setQa(list => [...list, r])
    } catch (e) { show(e.message, true) } finally { setAsking(false) }
  }

  const markDone = async (lead, e) => {
    e?.stopPropagation()
    try {
      await api.markPitchDone(lead.id)
      setLeadSel(s => { const n = new Set(s); n.delete(lead.id); return n })
      setLeads(list => list.filter(l => l.id !== lead.id))
      setLeadTotal(t => Math.max(0, t - 1))
      if (open?.id === lead.id) { setOpen(null); setPitch(null); setHistory([]) }
      show('Marked done — moved out of queue (still in All pitches)')
    } catch (err) { show(err.message, true) }
  }


    const toggleLeadSel = (id, e) => {
    e?.stopPropagation()
    setLeadSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  }

  const removePitchLead = async (lead, e) => {
    e?.stopPropagation()
    if (!confirm(`Remove ${lead.name || lead.email} from Pitch Decker?`)) return
    try {
      await api.deleteLead(lead.id)
      setLeads(list => list.filter(l => l.id !== lead.id))
      setLeadTotal(t => Math.max(0, t - 1))
      setLeadSel(s => { const n = new Set(s); n.delete(lead.id); return n })
      if (open?.id === lead.id) { setOpen(null); setPitch(null); setHistory([]) }
      show('Removed from Pitch Decker')
    } catch (err) { show(err.message, true) }
  }

  const removeSelectedPitchLeads = async () => {
    if (!leadSel.size) return
    if (!confirm(`Remove ${leadSel.size} selected lead(s) from Pitch Decker?`)) return
    try {
      await api.bulkDeleteLeads([...leadSel])
      setLeads(list => list.filter(l => !leadSel.has(l.id)))
      setLeadTotal(t => Math.max(0, t - leadSel.size))
      if (open && leadSel.has(open.id)) { setOpen(null); setPitch(null); setHistory([]) }
      setLeadSel(new Set())
      show('Selected leads removed')
      loadLeads()
    } catch (err) { show(err.message, true) }
  }

    const deleteAllPitchQueue = async () => {
    if (!leadTotal) return
    if (!confirm(`Delete ALL ${leadTotal} lead(s) from the Pitch Decker queue? This cannot be undone.`)) return
    try {
      const ids = []
      let page = 1, pages = 1
      while (page <= pages) {
        const r = await api.leadsPaged(`page=${page}&per_page=200&pitch_pending=true`)
        const items = r.items || []
        items.forEach(l => ids.push(l.id))
        pages = r.pages || 1
        page += 1
        if (!items.length) break
      }
      if (!ids.length) { show('Queue already empty'); return }
      for (let i = 0; i < ids.length; i += 500) {
        await api.bulkDeleteLeads(ids.slice(i, i + 500))
      }
      setLeads([]); setLeadTotal(0); setLeadSel(new Set())
      setOpen(null); setPitch(null); setHistory([])
      show(`Deleted ${ids.length} pitch-queue lead(s)`)
      loadLeads()
    } catch (err) { show(err.message, true) }
  }

  // Get back = undo mark-done → lead returns to main Pitch list
  const getBack = async (leadId, e) => {
    e?.stopPropagation()
    try {
      await api.unmarkPitchDone(leadId)
      show('Lead restored to Pitch Decker queue')
      loadLeads()
    } catch (err) { show(err.message, true) }
  }

  const lines = (pitch?.transcript || '').split('\n').filter(l => l.trim())

  return (
    <>
      <div className="pitch-intro card mb">
        <MiniOrb size={52} color="#0054FC" accent="#00BAFF" />
        <div style={{ flex: 1 }}>
          <b>How the Pitch Decker works</b>
          <p className="sm mut mt">
            Pick a lead → {osaja ? 'Osaja' : 'your agent'} runs fresh DuckDuckGo research
            (company, website, industry, AI signals, recent news) and builds a human,
            consultant-style discovery transcript — not a hard sales pitch. If no real pain
            is found, the transcript stays honest and only offers a light enhancement if it
            makes sense. Use “Client picked up” for real call notes. Ask free-form questions
            about objections or angles anytime.
          </p>
        </div>
                <div className="row" style={{ gap: 8, alignItems: 'center' }}>
          <label className="btn primary small" style={{ cursor: 'pointer', margin: 0 }}>
            + Upload Excel / CSV
            <input
              type="file"
              accept=".xlsx,.xls,.csv"
              style={{ display: 'none' }}
              onChange={async (e) => {
                const file = e.target.files?.[0]
                e.target.value = ''
                if (!file) return
                try {
                  const r = await api.uploadLeads(file, null, null, 'pitch')
                  show(`Pitch queue: ${r.created} added · ${r.skipped_duplicates || 0} dupes · ${r.unverified || 0} unverified`)
                  loadLeads()
                } catch (err) {
                  show(err.message || String(err), true)
                }
              }}
            />
          </label>
          <button className="btn ghost small" onClick={() => setShowAll(s => !s)}>
            {showAll ? '← Back to Decker' : <><IconArchive /> All pitches</>}
          </button>
        </div>
      </div>

      {showAll ? (
        <>
          <div className="records-filter card mb">
            <span className="sm mut">{records.total} pitch records — real-time, refreshes every 15s</span>
            <div className="row" style={{ gap: 8 }}>
              {recSel.size > 0 && (
                <button className="btn danger small" onClick={bulkDeleteRecords}>
                  <IconTrash /> Delete {recSel.size} selected
                </button>
              )}
              <button className="btn danger small" onClick={async () => {
                if (!confirm(`Delete ALL ${records.total} pitch records?`)) return
                try {
                  await api.deleteAllPitches()
                  setRecSel(new Set()); loadRecords(); show('All pitches deleted')
                } catch (e) { show(e.message, true) }
              }}>
                <IconTrash /> Delete all
              </button>
            </div>
          </div>
          <div className="card records-table-card">
            {records.items.length === 0 && <div className="empty">No pitch records yet.</div>}
            {records.items.length > 0 && (
              <table className="records-table">
                <thead>
                  <tr>
                    <th style={{ width: 34 }}>
                      <input type="checkbox" style={{ width: 16 }}
                             checked={records.items.length > 0 && recSel.size === records.items.length}
                             onChange={toggleRecAll} />
                    </th>
                    <th>Lead</th><th>Company</th><th>Country</th><th>Built</th>
                    <th style={{ width: 120 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {records.items.map(r => (
                    <React.Fragment key={r.id}>
                      <tr className={`record-row ${recOpen === r.id ? 'open' : ''}`}
                          onClick={() => setRecOpen(recOpen === r.id ? null : r.id)}>
                        <td onClick={e => e.stopPropagation()}>
                          <input type="checkbox" style={{ width: 16 }} checked={recSel.has(r.id)} onChange={() => toggleRecSel(r.id)} />
                        </td>
                        <td><b>{r.lead_name || '—'}</b></td>
                        <td>{r.company || '—'}</td>
                        <td>{r.country || '—'}</td>
                        <td className="sm mut">{new Date(r.created_at + 'Z').toLocaleString()}</td>
                        <td onClick={e => e.stopPropagation()}>
                          <div className="row" style={{ gap: 4, justifyContent: 'flex-end' }}>
                            {r.lead_id && (
                              <button
                                className="btn ghost small"
                                title="Put this lead back into the Pitch Decker queue"
                                onClick={(e) => getBack(r.lead_id, e)}
                              >
                                ↩ Get back
                              </button>
                            )}
                            <button className="icon-btn danger" onClick={(e) => { e.stopPropagation(); deleteOneRecord(r.id) }}>
                              <IconTrash />
                            </button>
                          </div>
                        </td>
                      </tr>
                      {recOpen === r.id && (
                        <tr className="record-detail">
                          <td colSpan={6}>
                            <div className="record-body">
                              {r.summary && <p className="sm" style={{ marginBottom: 8 }}><b>Summary:</b> {r.summary}</p>}
                              <pre>{r.transcript}</pre>
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
          <div className="pager mt">
            <button className="btn ghost small" disabled={recPage <= 1} onClick={() => setRecPage(p => p - 1)}>← Prev</button>
            <span className="sm mut">Page {records.page} of {records.pages} · {records.total} records</span>
            <button className="btn ghost small" disabled={recPage >= records.pages} onClick={() => setRecPage(p => p + 1)}>Next →</button>
          </div>
        </>
      ) : (
      <div className="pitch-layout">
        <div className="card pitch-list">
          <div className="topbar-search mb" style={{ minWidth: 0 }}>
            <IconUsers />
            <input placeholder="Search leads…" value={query} onChange={e => setQuery(e.target.value)} />
          </div>
          <div className="row mb" style={{ gap: 8, padding: '0 10px', alignItems: 'center', flexWrap: 'wrap' }}>
            {leadSel.size > 0 && (
              <>
                <span className="sm mut">{leadSel.size} selected</span>
                <button className="btn danger small" onClick={removeSelectedPitchLeads}>
                  <IconTrash /> Delete selected
                </button>
                <button className="btn ghost small" onClick={() => setLeadSel(new Set())}>Clear</button>
              </>
            )}
            {leadTotal > 0 && (
              <button className="btn danger small" onClick={deleteAllPitchQueue} style={{ marginLeft: 'auto' }}>
                <IconTrash /> Delete all ({leadTotal})
              </button>
            )}
          </div>
          <div className="pitch-list-scroll">
            {leads.length === 0 && <div className="empty">{leadsLoading ? 'Loading…' : 'No leads match'}</div>}
            {leads.map(l => (
              <div key={l.id} className={`pitch-lead-row ${open?.id === l.id ? 'on' : ''}`} onClick={() => select(l)}>
                <input
                  type="checkbox"
                  style={{ width: 15, marginRight: 6 }}
                  checked={leadSel.has(l.id)}
                  onChange={(e) => toggleLeadSel(l.id, e)}
                  onClick={(e) => e.stopPropagation()}
                  title="Select to delete"
                />
                <div className="avatar-fallback">{(l.name || l.email || '?')[0].toUpperCase()}</div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <b className="ellipsis">{l.name || l.email}</b>
                  <div className="sm mut ellipsis">{l.company || '—'} · {l.country || '—'}</div>
                </div>
                <span className={`pill ${l.temperature}`}>{l.temperature}</span>
                <button
                  className="icon-btn"
                  title="Mark as done"
                  onClick={(e) => markDone(l, e)}
                  style={{ marginLeft: 4 }}
                >
                  ✓
                </button>
                <button
                  className="icon-btn danger"
                  title="Delete from Pitch Decker"
                  onClick={(e) => removePitchLead(l, e)}
                  style={{ marginLeft: 2 }}
                >
                  <IconTrash />
                </button>
              </div>
            ))}
          </div>
          <div className="pager mt" style={{ padding: '8px 10px' }}>
            <button className="btn ghost small" disabled={leadPage <= 1 || leadsLoading}
                    onClick={() => setLeadPage(p => p - 1)}>← Prev</button>
            <span className="sm mut">Page {leadPage}/{leadPages} · {leadTotal} pending</span>
            <button className="btn ghost small" disabled={leadPage >= leadPages || leadsLoading}
                    onClick={() => setLeadPage(p => p + 1)}>Next →</button>
          </div>
        </div>

        <div className="card pitch-panel">
          {!open && (
            <div className="empty" style={{ minHeight: 340 }}>
              <IconRocket style={{ width: 30, height: 30, opacity: .35, marginBottom: 10 }} />
              <div>Select a lead on the left to build or review a pitch</div>
            </div>
          )}
          {open && (
            <>
              <div className="pitch-header">
                <div className="avatar-fallback lg">{(open.name || open.email)[0].toUpperCase()}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <h3>{open.name || open.email}</h3>
                  <div className="sm mut">{open.title ? open.title + ' · ' : ''}{open.company || '—'}</div>
                  {open.website && (
                    <div className="sm" style={{ marginTop: 2 }}>
                      <a href={open.website.startsWith('http') ? open.website : `https://${open.website}`}
                         target="_blank" rel="noreferrer"
                         style={{ color: 'var(--blue)', textDecoration: 'none' }}>
                        {open.website.replace(/^https?:\/\//, '')}
                      </a>
                    </div>
                  )}
                </div>
                <button className="btn" disabled={busy || aiDisabled} onClick={generate}
                  title={aiDisabled ? 'OpenAI API key required — configure in Super Admin' : undefined}>
                  {busy ? <span className="spinner" /> : null}
                  {aiDisabled ? '🔑 Key required' : (busy ? ' Building…' : history.length ? 'Regenerate pitch' : 'Build pitch')}
                </button>
              </div>

              <div className="pitch-panel-body" ref={panelBodyRef}>
                <div className="card" style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', marginBottom: 14, padding: '12px 14px' }}>
                  <div className="sm" style={{ fontWeight: 600, marginBottom: 6 }}>
                    ☎ Client picked up the phone?
                  </div>
                  <div className="sm mut" style={{ marginBottom: 8 }}>
                    Write what happened in plain words — their mood, what they said, any objections, outcome (booked / not interested / call later). The transcript will match your notes exactly and stay human, not salesy.
                  </div>
                  <textarea
                    rows={3}
                    placeholder={'e.g. "They picked up, seemed busy but curious. Said they struggle with customer response time. Open to a call next week. Didn\'t commit but said reply yes."'}
                    value={callNotes}
                    onChange={e => setCallNotes(e.target.value)}
                    style={{ width: '100%', resize: 'vertical', fontSize: 13, padding: '8px 10px', borderRadius: 6, border: '1px solid #d1fae5', marginBottom: 8 }}
                  />
                  <button className="btn small" disabled={callBusy || !callNotes.trim() || aiDisabled} onClick={generateFromCall}
                    title={aiDisabled ? 'OpenAI API key required — configure in Super Admin' : undefined}>
                    {aiDisabled ? '🔑 Key required' : (callBusy ? <><span className="spinner" /> Building…</> : 'Build transcript from call notes')}
                  </button>
                </div>

                <div className="row wrap mb sm" style={{ marginTop: 4 }}>
                  <span className="pill blue">☎ {open.phone || 'no phone'}</span>
                  <span className="pill gray">✉ {open.email}</span>
                  <span className="pill gray">{open.country || 'unknown region'}</span>
                  {open.website && (
                    <a className="pill gray" href={open.website.startsWith('http') ? open.website : `https://${open.website}`}
                       target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                      🌐 {open.website.replace(/^https?:\/\//, '')}
                    </a>
                  )}
                  <span className={`pill ${open.email_verified === false ? '' : 'ok'}`}
                        style={open.email_verified === false ? { background: '#fee2e2', color: '#b91c1c' } : undefined}>
                    {open.email_verified === false ? 'unverified' : 'verified'}
                  </span>
                </div>

                {history.length > 1 && (
                  <div className="row wrap mb sm">
                    {history.map(p => (
                      <button key={p.id} className={`btn ghost small ${pitch?.id === p.id ? 'on' : ''}`}
                              onClick={() => setPitch(p)}>
                        {new Date(p.created_at + 'Z').toLocaleDateString()}
                      </button>
                    ))}
                  </div>
                )}

                {busy && (
                  <div className="pitch-skeleton">
                    <div className="skeleton" style={{ height: 60, marginBottom: 14 }} />
                    {[0, 1, 2, 3].map(i => (
                      <div key={i} className="skeleton" style={{ height: 34, width: `${70 - i * 8}%`, marginBottom: 10 }} />
                    ))}
                  </div>
                )}

                {!busy && pitch && (
                  <>
                    {pitch.summary && (
                      <div className="pitch-summary">
                        <b className="sm">How it closed</b>
                        <p className="sm" style={{ marginTop: 4 }}>{pitch.summary}</p>
                      </div>
                    )}
                    <div className="thread" ref={threadRef}>
                      {lines.map((ln, i) => {
                        const isAgent = /^(osaja|saif|aleem|dawood|agent)\b/i.test(ln.trim())
                        const idx = ln.indexOf(':')
                        const who = idx > 0 && idx < 24 ? ln.slice(0, idx) : ''
                        const text = idx > 0 && idx < 24 ? ln.slice(idx + 1).trim() : ln
                        return (
                          <div key={i} className={`bubble ${isAgent ? 'out' : 'in'} bubble-reveal`}
                               style={{ animationDelay: `${Math.min(i * 70, 900)}ms` }}>
                            {who && <div className="meta">{who}</div>}
                            {text}
                          </div>
                        )
                      })}
                    </div>
                    <div className="row mt">
                      <button className="btn danger small" onClick={() => removePitch(pitch.id)}>Delete this pitch</button>
                    </div>
                  </>
                )}
                {!busy && !pitch && (
                  <div className="empty">No pitch yet — click "Build pitch" to generate one from live DuckDuckGo research</div>
                )}

                <div className="ask-box">
                  <b className="sm">Ask {osaja?.name || 'the agent'} about this lead</b>
                  <div className="row mt" style={{ gap: 8 }}>
                    <input placeholder='e.g. "How do I handle the pricing objection here?"'
                           value={ask} onChange={e => setAsk(e.target.value)}
                           onKeyDown={e => e.key === 'Enter' && !asking && askQuestion()} />
                    <button className="btn" disabled={asking || !ask.trim() || aiDisabled} onClick={askQuestion}
                      title={aiDisabled ? 'OpenAI API key required — configure in Super Admin' : undefined}>
                      {aiDisabled ? '🔑' : (asking ? <span className="spinner" /> : 'Ask')}
                    </button>
                  </div>
                  {qa.length > 0 && (
                    <div className="qa-list">
                      {qa.map((item, i) => (
                        <div key={i} className="qa-item bubble-reveal">
                          <div className="qa-q">You asked: "{item.question}"</div>
                          <div className="qa-a"><b>{item.agent}:</b> {item.answer}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
      )}
      <Toast toast={toast} />
    </>
  )
}