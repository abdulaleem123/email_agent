import React, { useEffect, useState, useCallback } from 'react'
import { api } from '../api.js'
import MiniOrb from '../MiniOrb.jsx'
import { Toast, useToast } from '../App.jsx'
import { IconMic, IconUsers, IconRocket, IconArchive, IconTrash } from '../Icons.jsx'

export default function Pitch() {
  const [leads, setLeads] = useState([])
  const [agents, setAgents] = useState([])
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(null)        // selected lead
  const [pitch, setPitch] = useState(null)      // current transcript record
  const [history, setHistory] = useState([])    // past pitches for this lead
  const [busy, setBusy] = useState(false)
  const [ask, setAsk] = useState('')
  const [asking, setAsking] = useState(false)
  const [qa, setQa] = useState([])              // [{question, answer, agent}]
  const [toast, show] = useToast()

  // "All pitches" browser — every pitch ever generated, paginated, real-time
  const [showAll, setShowAll] = useState(false)
  const [records, setRecords] = useState({ items: [], total: 0, page: 1, pages: 1 })
  const [recPage, setRecPage] = useState(1)
  const [recSel, setRecSel] = useState(new Set())
  const [recOpen, setRecOpen] = useState(null)

  const loadRecords = useCallback(() => {
    api.pitchRecords(`page=${recPage}&per_page=20`).then(setRecords).catch(e => show(e.message, true))
  }, [recPage, show])
  useEffect(() => { if (showAll) loadRecords() }, [showAll, loadRecords])
  useEffect(() => {
    if (!showAll) return
    const t = setInterval(loadRecords, 15000)   // real-time refresh, no cache
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

  useEffect(() => {
    api.leads('?per_page=300').then(setLeads).catch(e => show(e.message, true))
    api.agents().then(setAgents).catch(() => {})
  }, [])

  const osaja = agents.find(a => a.name.toLowerCase() === 'osaja')

  const select = async (lead) => {
    setOpen(lead); setPitch(null); setQa([])
    const list = await api.pitches(lead.id).catch(() => [])
    setHistory(list)
    if (list.length) setPitch(list[0])
  }

  const generate = async () => {
    if (!open) return
    setBusy(true); setPitch(null)
    show('Osaja is researching and building the pitch…')
    try {
      const rec = await api.generatePitch(open.id, osaja?.id)
      setPitch(rec)
      setHistory(h => [rec, ...h])
      show('Pitch ready — saved to records')
    } catch (e) { show(e.message, true) } finally { setBusy(false) }
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

  const filteredLeads = leads.filter(l => {
    if (!query.trim()) return true
    const s = query.toLowerCase()
    return (l.name || '').toLowerCase().includes(s) || (l.company || '').toLowerCase().includes(s)
      || (l.email || '').toLowerCase().includes(s)
  })

  const lines = (pitch?.transcript || '').split('\n').filter(l => l.trim())

  return (
    <>
      <div className="pitch-intro card mb">
        <MiniOrb size={52} color="#0054FC" accent="#00BAFF" />
        <div style={{ flex: 1 }}>
          <b>How the Pitch Decker works</b>
          <p className="sm mut mt">
            Pick a lead → {osaja ? 'Osaja' : 'your sales agent'} pulls the cached research
            (company, person, website, country — no extra Tavily credits spent) and role-plays
            a full sales call in that market's psychology, ending in a close. Every transcript
            is saved. You can also ask a direct question below — "how do I handle the pricing
            objection here?" — and get a grounded, short answer.
          </p>
        </div>
        <button className="btn ghost small" onClick={() => setShowAll(s => !s)}>
          {showAll ? '← Back to Decker' : <><IconArchive /> All pitches</>}
        </button>
      </div>

      {showAll ? (
        <>
          <div className="records-filter card mb">
            <span className="sm mut">{records.total} pitch records — real-time, refreshes every 15s</span>
            {recSel.size > 0 && (
              <button className="btn danger small" onClick={bulkDeleteRecords}>
                <IconTrash /> Delete {recSel.size} selected
              </button>
            )}
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
                    <th>Lead</th><th>Company</th><th>Country</th><th>Built</th><th style={{ width: 44 }}></th>
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
                        <td>
                          <button className="icon-btn danger" onClick={(e) => { e.stopPropagation(); deleteOneRecord(r.id) }}>
                            <IconTrash />
                          </button>
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
        {/* left: lead picker */}
        <div className="card pitch-list">
          <div className="topbar-search mb" style={{ minWidth: 0 }}>
            <IconUsers />
            <input placeholder="Search leads…" value={query} onChange={e => setQuery(e.target.value)} />
          </div>
          <div className="pitch-list-scroll">
            {filteredLeads.length === 0 && <div className="empty">No leads match</div>}
            {filteredLeads.map(l => (
              <div key={l.id} className={`pitch-lead-row ${open?.id === l.id ? 'on' : ''}`} onClick={() => select(l)}>
                <div className="avatar-fallback">{(l.name || l.email || '?')[0].toUpperCase()}</div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <b className="ellipsis">{l.name || l.email}</b>
                  <div className="sm mut ellipsis">{l.company || '—'} · {l.country || '—'}</div>
                </div>
                <span className={`pill ${l.temperature}`}>{l.temperature}</span>
              </div>
            ))}
          </div>
        </div>

        {/* right: transcript + ask panel */}
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
                </div>
                <button className="btn" disabled={busy} onClick={generate}>
                  {busy ? <span className="spinner" /> : null}
                  {busy ? ' Building…' : history.length ? 'Regenerate pitch' : 'Build pitch'}
                </button>
              </div>

              <div className="row wrap mb sm" style={{ marginTop: 4 }}>
                <span className="pill blue">☎ {open.phone || 'no phone'}</span>
                <span className="pill gray">✉ {open.email}</span>
                <span className="pill gray">{open.country || 'unknown region'}</span>
                {open.website && <span className="pill gray">{open.website}</span>}
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
                  <div className="thread">
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
                <div className="empty">No pitch yet — click "Build pitch" to generate one</div>
              )}

              {/* Ask Osaja — free-form query about this lead */}
              <div className="ask-box">
                <b className="sm">Ask {osaja?.name || 'the agent'} about this lead</b>
                <div className="row mt" style={{ gap: 8 }}>
                  <input placeholder='e.g. "How do I handle the pricing objection here?"'
                         value={ask} onChange={e => setAsk(e.target.value)}
                         onKeyDown={e => e.key === 'Enter' && !asking && askQuestion()} />
                  <button className="btn" disabled={asking || !ask.trim()} onClick={askQuestion}>
                    {asking ? <span className="spinner" /> : 'Ask'}
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
            </>
          )}
        </div>
      </div>
      )}
      <Toast toast={toast} />
    </>
  )
}