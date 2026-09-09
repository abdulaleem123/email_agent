import React, { useEffect, useRef, useState, useCallback } from 'react'
import { api } from '../api.js'
import MiniOrb from '../MiniOrb.jsx'
import { Toast, useToast, useOpenAIKey } from '../App.jsx'
import { IconSend, IconPause, IconRefresh, IconMail } from '../Icons.jsx'

/**
 * Messages — all conversations across all agent inboxes.
 * Paginated threads, realtime polling, distinct bubbles for prospect/AI/you,
 * per-agent play/pause with immediate effect.
 */
export default function Inbox() {
  const { openaiReady } = useOpenAIKey()
  const aiDisabled = openaiReady === false
  const [agents, setAgents] = useState([])
  const [agentId, setAgentId] = useState(0)
  const [convos, setConvos] = useState([])
  const [convoPage, setConvoPage] = useState(1)
  const [convoTotal, setConvoTotal] = useState(0)
  const [convoPages, setConvoPages] = useState(1)
  const [convoQ, setConvoQ] = useState('')
  const [open, setOpen] = useState(null)
  const [thread, setThread] = useState(null)
  const [threadPage, setThreadPage] = useState(1)
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [sending, setSending] = useState(false)
  const [live, setLive] = useState(true)
  const lastSeenId = useRef(0)
  const [toast, show] = useToast()

  useEffect(() => { api.agents().then(setAgents).catch(() => {}) }, [])

  const loadConvos = useCallback(() => {
    const params = new URLSearchParams({ page: convoPage, per_page: 20 })
    if (agentId) params.set('agent_id', agentId)
    if (convoQ.trim()) params.set('q', convoQ.trim())
    api.inboxPaged(params.toString())
      .then(r => {
        const d = Array.isArray(r) ? { items: r, total: r.length, pages: 1 } : r
        setConvos(d.items || [])
        setConvoTotal(d.total || 0)
        setConvoPages(d.pages || 1)
      })
      .catch(() => setConvos([]))
  }, [agentId, convoPage, convoQ])

  useEffect(() => { loadConvos() }, [loadConvos])

  const loadThread = useCallback(async (leadId, page = 1) => {
    try {
      const t = await api.thread(leadId, page, 20)
      setThread(t)
      setThreadPage(page)
      if (t.items?.length) {
        const maxId = Math.max(...t.items.map(m => m.id))
        lastSeenId.current = Math.max(lastSeenId.current, maxId)
      }
      const inbound = [...(t.items || [])].reverse().find(m => m.direction === 'in')
      if (inbound && page === 1) {
        setSubject(inbound.subject?.startsWith('Re:') ? inbound.subject : `Re: ${inbound.subject || ''}`)
      }
    } catch (e) { show(e.message, true) }
  }, [show])

  const openConvo = async (c) => {
    setOpen(c); setBody(''); setSubject('')
    await loadThread(c.lead_id, 1)
  }

  useEffect(() => {
    if (!live) return
    const t = setInterval(async () => {
      try {
        const items = await api.feed(lastSeenId.current, agentId || undefined)
        if (Array.isArray(items) && items.length) {
          lastSeenId.current = Math.max(...items.map(m => m.id), lastSeenId.current)
          loadConvos()
          if (open && items.some(m => m.lead_id === open.lead_id)) {
            loadThread(open.lead_id, threadPage)
          }
        }
      } catch {}
    }, 5000)
    return () => clearInterval(t)
  }, [live, agentId, open, threadPage, loadConvos, loadThread])

  const send = async () => {
    if (!subject.trim() || !body.trim() || !open) return
    setSending(true)
    try {
      await api.manualSend(open.lead_id, subject, body)
      setBody('')
      await loadThread(open.lead_id, threadPage)
      show('Email sent from your account')
    } catch (e) { show(e.message, true) } finally { setSending(false) }
  }

  const deleteConvo = async (leadId) => {
    if (!confirm('Remove this conversation? The lead will be deleted.')) return
    try { await api.deleteLead(leadId); if (open?.lead_id === leadId) setOpen(null); loadConvos(); show('Removed') }
    catch (e) { show(e.message, true) }
  }

  const toggleAgent = async (a) => {
    const r = await api.toggleAgent(a.id)
    setAgents(list => list.map(x => x.id === a.id ? { ...x, is_active: r.is_active } : x))
    show(`${a.name} ${r.is_active ? 'resumed' : 'paused'}`)
  }

  const toggleLeadAi = async () => {
    if (!open) return
    const r = await api.toggleLeadAi(open.lead_id)
    setThread(t => ({ ...t, lead: { ...t.lead, ai_paused: r.ai_paused } }))
    setConvos(list => list.map(c => c.lead_id === open.lead_id ? { ...c, ai_paused: r.ai_paused } : c))
    show(r.ai_paused
      ? 'AI paused for this conversation — reply manually below, nothing sends automatically'
      : 'AI resumed for this conversation')
  }

  const current = agents.find(a => a.id === agentId)
  const totalPages = thread ? Math.max(1, thread.pages || 1) : 1

  return (
    <>
      <div className="messages-intro card mb">
        <MiniOrb size={52} color="#0054FC" accent="#00BAFF" />
        <div style={{ flex: 1 }}>
          <b>Every conversation, every direction, in one place</b>
          <p className="sm mut mt">
            <b>AI Live</b> means the agent is active and will auto-reply to inbound emails (after the
            configured inbound delay) and send scheduled outbound emails. Pausing stops <em>both</em> inbound
            auto-replies and outbound sends for that agent. Inbound/outbound timing is set on the
            Settings page in real-time — no restart needed. You can also pause AI per-conversation below.
          </p>
        </div>
        <button className={`icon-btn ${live ? 'on' : ''}`} onClick={() => setLive(l => !l)}
                title={live ? 'Realtime on' : 'Realtime paused'}>
          <IconRefresh />
        </button>
      </div>

      <div className="agent-tabs">
        <button className={agentId === 0 ? 'on' : ''} onClick={() => setAgentId(0)}>All inboxes</button>
        {agents.map(a => (
          <button key={a.id} className={agentId === a.id ? 'on' : ''} onClick={() => setAgentId(a.id)}>
            <img src={`/${a.name.toLowerCase()}.png`} alt="" className="tab-avatar"
                 onError={(e) => { e.target.style.display = 'none' }} />
            {a.name} {a.is_active ? <span className="live-dot" /> : <IconPause style={{ width: 12, height: 12 }} />}
          </button>
        ))}
      </div>

      {current && (
        <div className="card mb agent-strip-card">
          <img src={`/${current.name.toLowerCase()}.png`} alt="" className="agent-avatar-md"
               onError={(e) => { e.target.style.display = 'none' }} />
          <div style={{ flex: 1 }}>
            <b>{current.name}</b>
            <div className="sm mut">{current.role}</div>
          </div>
          <div className="row" style={{ gap: 10 }}>
            <span className="sm mut">{current.is_active ? 'Replying live' : 'Paused — you handle manually'}</span>
            <div className={`switch ${current.is_active ? 'on' : ''}`} onClick={() => toggleAgent(current)} role="button" />
          </div>
        </div>
      )}

      <div className="row between mb" style={{ gap: 8 }}>
        <input style={{ flex: 1, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--line)', fontSize: 13 }}
               placeholder="Search conversations…" value={convoQ}
               onChange={e => { setConvoQ(e.target.value); setConvoPage(1) }} />
        <span className="sm mut">{convoTotal} total</span>
      </div>

      <div className="card" style={{ padding: 0 }}>
        {(!Array.isArray(convos) || convos.length === 0) && <div className="empty">No conversations yet.</div>}
        {(Array.isArray(convos) ? convos : []).map(c => (
          <div key={c.lead_id} className={`convo ${open?.lead_id === c.lead_id ? 'on' : ''}`}>
            <div className="avatar-fallback" onClick={() => openConvo(c)} style={{ cursor: 'pointer' }}>{(c.name || c.email || '?')[0].toUpperCase()}</div>
            <div style={{ flex: 1, minWidth: 0, cursor: 'pointer' }} onClick={() => openConvo(c)}>
              <div className="row between">
                <b className="ellipsis">{c.name || c.email}</b>
                <span className="sm mut">{c.last_at ? new Date(c.last_at + 'Z').toLocaleString() : ''}</span>
              </div>
              <div className="sm mut ellipsis">
                {c.company}
                {c.ai_paused && <span className="pill" style={{ background: '#fee2e2', color: '#b91c1c', marginLeft: 6 }}>AI paused</span>}
              </div>
              <div className="snip ellipsis">
                {c.last_direction === 'in' ? '↩ ' : '→ '}
                <b>{c.last_subject}</b> — {c.last_snippet}
              </div>
            </div>
            <div style={{ textAlign: 'right', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
              <span className={`pill ${c.temperature}`}>{c.temperature}</span>
              <div className="sm mut">{c.message_count} msgs</div>
              <button className="btn danger small" style={{ padding: '2px 6px', fontSize: 11 }}
                      onClick={e => { e.stopPropagation(); deleteConvo(c.lead_id) }} title="Remove conversation">✕</button>
            </div>
          </div>
        ))}
      </div>

      {convoPages > 1 && (
        <div className="pagination mt">
          <button disabled={convoPage <= 1} onClick={() => setConvoPage(p => p - 1)}>‹</button>
          <span className="sm mut">Page {convoPage} of {convoPages}</span>
          <button disabled={convoPage >= convoPages} onClick={() => setConvoPage(p => p + 1)}>›</button>
        </div>
      )}

      {open && thread && (
        <div className="drawer-veil" onClick={e => e.target === e.currentTarget && setOpen(null)}>
          <div className="drawer">
            <div className="drawer-head">
              <div className="avatar-fallback lg">{(open.name || open.email || '?')[0].toUpperCase()}</div>
              <div style={{ flex: 1 }}>
                <h2 style={{ fontSize: 18, margin: 0 }}>{open.name || open.email}</h2>
                <div className="sm mut">{open.company} · handled by <b>{thread.lead?.agent_name || 'unassigned'}</b></div>
              </div>
              <button className={`btn small ${thread.lead?.ai_paused ? 'danger' : 'ghost'}`} onClick={toggleLeadAi}
                      title="Pause/resume AI for just this conversation — doesn't affect the agent's other leads">
                {thread.lead?.ai_paused ? <><IconPause /> AI paused here</> : <>▶ AI live here</>}
              </button>
              <button className="icon-btn" onClick={() => setOpen(null)} title="Close">✕</button>
            </div>
            {thread.lead?.ai_paused && (
              <div className="err mb sm">
                You've taken over this conversation — the agent won't auto-reply or send follow-ups
                to {open.name || open.email} until you resume it.
              </div>
            )}

            {thread.total > 20 && (
              <div className="thread-pager sm mut">
                <button className="btn ghost small" disabled={threadPage <= 1}
                        onClick={() => loadThread(open.lead_id, threadPage - 1)}>← Older</button>
                <span>Page {threadPage} of {totalPages} · {thread.total} messages</span>
                <button className="btn ghost small" disabled={threadPage >= totalPages}
                        onClick={() => loadThread(open.lead_id, threadPage + 1)}>Newer →</button>
              </div>
            )}

            <div className="thread mb">
              {thread.items.map(m => {
                const kind = m.direction === 'in' ? 'in' : (m.sent_by === 'user' ? 'user' : 'agent')
                const who = kind === 'in' ? (open.name || open.email)
                          : kind === 'user' ? 'You (manual takeover)'
                          : (thread.lead?.agent_name || 'Agent')
                return (
                  <div key={m.id} className={`bubble bubble-${kind}`}>
                    <div className="meta">
                      <b>{who}</b>
                      <span className="sm mut"> · {new Date(m.created_at + 'Z').toLocaleString()}</span>
                      {m.html_used ? <span className="sm mut"> · template</span> : null}
                    </div>
                    {m.subject && <div className="subj">{m.subject}</div>}
                    <div className="body-text">{m.body}</div>
                  </div>
                )
              })}
            </div>

            <div className="card compose-card">
              <div className="row between mb">
                <b className="sm">Send manually from your account</b>
                <span className="sm mut">The AI will see this in the next thread turn</span>
              </div>
              <div className="field">
                <label>Subject</label>
                <input value={subject} onChange={e => setSubject(e.target.value)} placeholder="Re: …" />
              </div>
              <div className="field">
                <label>Message (plain text)</label>
                <textarea rows={4} value={body} onChange={e => setBody(e.target.value)} placeholder="Write your reply…" />
              </div>
              <button className="btn" onClick={send} disabled={sending || !body.trim() || !subject.trim() || aiDisabled}
                title={aiDisabled ? 'OpenAI API key required — configure in Super Admin' : undefined}>
                {aiDisabled ? '🔑 Key required' : (sending ? <><span className="spinner" /> &nbsp;Sending…</> : <><IconSend /> &nbsp;Send now</>)}
              </button>
            </div>
          </div>
        </div>
      )}
      <Toast toast={toast} />
    </>
  )
}