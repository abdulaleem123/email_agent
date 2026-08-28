import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import MiniOrb from '../MiniOrb.jsx'
import { Toast, useToast } from '../App.jsx'
import Counter from '../Counter.jsx'
import { IconRocket, IconPlus, IconTrash } from '../Icons.jsx'

const BLANK = { name: '', goal: '', strategy: 'B2B', template_mode: 'template', batch_size: 30, agent_id: '',
  email_length: 'concise', what_to_sell: '', what_to_avoid: '', target_focus: '', target_country: '' }

export default function Campaigns() {
  const [campaigns, setCampaigns] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const perPage = 20
  const [agents, setAgents] = useState([])
  const [form, setForm] = useState(null)
  const [batchesFor, setBatchesFor] = useState({})
  const [showHow, setShowHow] = useState(false)
  const [toast, show] = useToast()

  const load = async () => {
    const [cp, ags] = await Promise.all([api.campaignsPaged(page, perPage), api.agents()])
    setCampaigns(cp.items); setTotal(cp.total); setPages(cp.pages)
    setAgents(ags)
    const map = {}
    await Promise.all(cp.items.map(async c => { map[c.id] = await api.batches(c.id).catch(() => []) }))
    setBatchesFor(map)
  }
  useEffect(() => { load().catch(e => show(e.message, true)) }, [page])
  useEffect(() => { const t = setInterval(() => load().catch(() => {}), 15000); return () => clearInterval(t) }, [page])

  const create = async () => {
    try {
      await api.createCampaign({ ...form, agent_id: +form.agent_id, batch_size: +form.batch_size })
      setForm(null); load(); show('Campaign created')
    } catch (e) { show(e.message, true) }
  }
  const toggle = async (c) => { await api.toggleCampaign(c.id); load() }
  const delCampaign = async (c) => {
    if (!confirm(`Delete campaign "${c.name}"?`)) return
    await api.deleteCampaign(c.id); load(); show('Campaign deleted')
  }
  const delBatch = async (b) => {
    await api.deleteBatch(b.id); load(); show(`Batch #${b.number} deleted`)
  }

  const agentName = id => agents.find(a => a.id === id)?.name || '—'
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const totalActive = campaigns.filter(c => c.status === 'active').length

  return (
    <>
      <div className="records-intro card mb">
        <MiniOrb size={52} color="#d97706" accent="#0054FC" />
        <div style={{ flex: 1 }}>
          <b>Campaigns — <Counter value={totalActive} /> active</b>
          <p className="sm mut mt">
            Each campaign tells one agent how to sell: target country, pain focus, what to pitch,
            what to avoid. Leads are enrolled in batches (20-50), spaced 1-5 minutes apart, with
            same-day dedupe across agents so no lead gets two emails on the same day.
          </p>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn ghost small" onClick={() => setShowHow(s => !s)}>{showHow ? 'Hide' : 'How this works'} →</button>
          <button className="btn" onClick={() => setForm({ ...BLANK, agent_id: agents[0]?.id || '' })}>
            <IconPlus /> New campaign
          </button>
        </div>
      </div>

      {showHow && (
        <div className="card mb explainer">
          <h3>How a campaign runs</h3>
          <ol>
            <li><b>You define the play</b>: agent, target country, pain focus, what to sell, what to avoid, email length, plain vs. template.</li>
            <li><b>Leads enroll</b> from the Leads page. Each lead gets researched with Tavily (company + person + website + country).</li>
            <li><b>Batches</b> of 20-50 form automatically. First email is template mode (with logo) or plain; follow-ups are always plain.</li>
            <li><b>Sending</b>: 1-5 min stagger inside a batch, per-agent daily send cap, same-day dedupe across agents (agent A emails a lead today → agent B waits till tomorrow).</li>
            <li><b>Replies</b> flow back through the agent's IMAP inbox. Agent auto-replies ~15 min later using its knowledge base. Weekend Calendly link when interest is real.</li>
            <li><b>Pause anytime</b>: switch the toggle → all new sends stop; in-flight batches finish gracefully. Delete individual batches to skip them.</li>
          </ol>
        </div>
      )}

      {campaigns.length === 0 && <div className="card empty">No campaigns yet. Create one, then enroll leads from the Leads page.</div>}

      {campaigns.map(c => (
        <div key={c.id} className="card mb">
          <div className="row between">
            <div>
              <b style={{ fontSize: 15 }}>{c.name}</b>
              <div className="sm mut">Agent: {agentName(c.agent_id)} · {c.strategy} · {c.template_mode === 'template' ? 'Template (HTML + logo)' : 'Plain text'} · batches of {c.batch_size}</div>
            </div>
            <div className="row">
              <span className={`pill ${c.status === 'active' ? 'ok' : 'gray'}`}>{c.status}</span>
              <div className={`switch ${c.status === 'active' ? 'on' : ''}`} onClick={() => toggle(c)} role="button" title="Pause / resume" />
              <button className="btn danger small" onClick={() => delCampaign(c)}>Delete</button>
            </div>
          </div>
          {c.goal && <p className="sm mut mt">{c.goal}</p>}
          {(batchesFor[c.id] || []).map(b => {
            const done = b.status === 'completed'
            const pct = b.total ? Math.round(((b.sent + b.failed) / b.total) * 100) : 0
            return (
              <div key={b.id} className={`batch ${done ? 'done' : ''}`}>
                <div className="row">
                  <b className="sm">Batch #{b.number}</b>
                  <span className={`pill ${done ? 'ok' : b.status === 'running' ? 'blue' : 'gray'}`}>{done ? '✓ completed' : b.status}</span>
                  <span className="sm mut">{b.sent}/{b.total} sent{b.failed ? ` · ${b.failed} failed` : ''}</span>
                </div>
                <div className="row">
                  <div className="bar"><i style={{ width: `${pct}%` }} /></div>
                  <button className="btn danger small" onClick={() => delBatch(b)} title="Delete this batch">Delete</button>
                </div>
              </div>
            )
          })}
        </div>
      ))}

      {form && (
        <div className="drawer-veil" onClick={e => e.target === e.currentTarget && setForm(null)}>
          <div className="drawer">
            <h2>New campaign</h2>
            <div className="field"><label>Name</label>
              <input value={form.name} onChange={e => set('name', e.target.value)} placeholder="Q3 US SaaS outreach" /></div>
            <div className="field"><label>Goal — what client need are we solving?</label>
              <textarea value={form.goal} onChange={e => set('goal', e.target.value)}
                placeholder="Book 30-min strategy sessions with ops leaders drowning in manual support" /></div>
            <div className="grid c2">
              <div className="field"><label>Strategy</label>
                <select value={form.strategy} onChange={e => set('strategy', e.target.value)}>
                  {['B2B', 'B2C', 'ABM', 'custom'].map(s => <option key={s}>{s}</option>)}
                </select></div>
              <div className="field"><label>Agent</label>
                <select value={form.agent_id} onChange={e => set('agent_id', e.target.value)}>
                  {agents.map(a => <option key={a.id} value={a.id}>{a.name} — {a.role}</option>)}
                </select></div>
              <div className="field"><label>First email format</label>
                <select value={form.template_mode} onChange={e => set('template_mode', e.target.value)}>
                  <option value="template">Template — HTML, Chatversio logo at bottom</option>
                  <option value="plain">Plain — simple professional text</option>
                </select></div>
              <div className="field"><label>Batch size (20–50)</label>
                <input type="number" min={20} max={50} value={form.batch_size} onChange={e => set('batch_size', e.target.value)} /></div>
              <div className="field"><label>Email length</label>
                <select value={form.email_length} onChange={e => set('email_length', e.target.value)}>
                  {['short', 'concise', 'long', 'professional'].map(l => <option key={l}>{l}</option>)}
                </select></div>
              <div className="field"><label>Target country (psychology override — optional)</label>
                <input value={form.target_country} onChange={e => set('target_country', e.target.value)} placeholder="e.g. UAE, United States, Germany" /></div>
            </div>
            <div className="field"><label>Pain focus (target/country-wise — what problem to anchor on)</label>
              <textarea value={form.target_focus} onChange={e => set('target_focus', e.target.value)}
                placeholder="e.g. manual customer support, leads leaving the website unanswered" /></div>
            <div className="field"><label>What to sell (pitch/emphasise exactly this)</label>
              <textarea value={form.what_to_sell} onChange={e => set('what_to_sell', e.target.value)}
                placeholder="e.g. industry-specialist AI chat agents that book leads 24/7" /></div>
            <div className="field"><label>What NOT to mention</label>
              <textarea value={form.what_to_avoid} onChange={e => set('what_to_avoid', e.target.value)}
                placeholder="e.g. exact pricing, competitor names" /></div>
            <p className="sm mut mb">Follow-ups and inbound replies are always sent as plain text — templates apply to the first touch only.</p>
            <div className="row">
              <button className="btn" onClick={create}>Create campaign</button>
              <button className="btn ghost" onClick={() => setForm(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {total > perPage && (
        <div className="pager mt">
          <button className="btn ghost small" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
          <span className="sm mut">Page {page} of {pages} · {total} campaigns</span>
          <button className="btn ghost small" disabled={page >= pages} onClick={() => setPage(p => p + 1)}>Next →</button>
        </div>
      )}
      <Toast toast={toast} />
    </>
  )
}