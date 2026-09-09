import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import MiniOrb from '../MiniOrb.jsx'
import { Toast, useToast, useOpenAIKey } from '../App.jsx'
import Counter from '../Counter.jsx'
import { IconRocket, IconPlus, IconTrash } from '../Icons.jsx'

// Smart presets — user picks one and fields auto-fill
const PRESETS = [
  {
    label: '🎯 B2B Cold Outreach',
    hint: 'Target businesses with a specific pain point',
    data: {
      strategy: 'B2B', template_mode: 'plain', batch_size: 30,
      email_length: 'concise',
      goal: 'Book discovery calls with decision-makers who have a specific operational pain',
      target_focus: 'manual processes, unanswered leads, slow customer support',
      what_to_sell: 'AI-powered automation that saves time and books leads 24/7',
      what_to_avoid: 'exact pricing, competitor names, aggressive language',
    }
  },
  {
    label: '🏢 Enterprise ABM',
    hint: 'Named account targeting, high-touch messaging',
    data: {
      strategy: 'ABM', template_mode: 'template', batch_size: 20,
      email_length: 'professional',
      goal: 'Open strategic conversations with C-suite and VP-level buyers at target accounts',
      target_focus: 'operational efficiency, cost reduction, competitive advantage',
      what_to_sell: 'Enterprise AI solutions tailored to their industry vertical',
      what_to_avoid: 'pricing in first email, generic claims, anything that sounds mass-market',
    }
  },
  {
    label: '🚀 SaaS Trial Push',
    hint: 'Get product signups or demos fast',
    data: {
      strategy: 'B2B', template_mode: 'plain', batch_size: 40,
      email_length: 'short',
      goal: 'Drive free trial signups or product demos with a single clear CTA',
      target_focus: 'inefficient current tools, time wasted on repetitive tasks',
      what_to_sell: 'Free trial or live demo — low commitment, immediate value',
      what_to_avoid: 'long explanations, multiple CTAs, pricing details',
    }
  },
  {
    label: '🌍 GCC / Middle East',
    hint: 'Region-specific tone for UAE, KSA, Qatar',
    data: {
      strategy: 'B2B', template_mode: 'template', batch_size: 25,
      email_length: 'professional',
      target_country: 'UAE',
      goal: 'Build trust and open a conversation — relationship first, pitch second',
      target_focus: 'digital transformation, customer experience, Vision 2030 alignment',
      what_to_sell: 'AI solutions that align with regional digital transformation goals',
      what_to_avoid: 'overly pushy tone, aggressive CTAs, Western-centric language',
    }
  },
]

const BLANK = {
  name: '', goal: '', strategy: 'B2B', template_mode: 'plain', batch_size: 30,
  email_length: 'concise', what_to_sell: '', what_to_avoid: '',
  target_focus: '', target_country: ''
}

export default function Campaigns() {
  const { openaiReady } = useOpenAIKey()
  const aiDisabled = openaiReady === false
  const [campaigns, setCampaigns] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const perPage = 20
  const [agents, setAgents] = useState([])
  const [form, setForm] = useState(null)
  const [batchesFor, setBatchesFor] = useState({})
  const [showHow, setShowHow] = useState(false)
  const [step, setStep] = useState(0) // 0=preset picker, 1=form
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

  const openNew = () => {
    setStep(0)
    setForm({ ...BLANK, agent_id: agents[0]?.id || '' })
  }

  const applyPreset = (preset) => {
    setForm(f => ({ ...f, ...preset.data }))
    setStep(1)
  }

  const skipPreset = () => setStep(1)

  const create = async () => {
    if (!form.name.trim()) { show('Campaign name is required', true); return }
    if (!form.agent_id) { show('Please select an agent', true); return }
    try {
      await api.createCampaign({ ...form, agent_id: +form.agent_id, batch_size: +form.batch_size })
      setForm(null); setStep(0); load(); show('Campaign created ✓')
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
            what to avoid. Leads enroll in batches, staggered so inboxes stay healthy.
          </p>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn ghost small" onClick={() => setShowHow(s => !s)}>{showHow ? 'Hide' : 'How this works'} →</button>
          <button className="btn" disabled={aiDisabled}
            title={aiDisabled ? 'OpenAI API key required — configure in Super Admin' : undefined}
            onClick={() => !aiDisabled && openNew()}>
            <IconPlus /> New campaign
          </button>
        </div>
      </div>

      {showHow && (
        <div className="card mb explainer">
          <h3>How a campaign runs</h3>
          <ol>
            <li><b>Pick a preset</b> — we auto-fill the strategy, tone, and pain focus. Tweak what you need.</li>
            <li><b>Leads enroll</b> from the Leads page. Each lead gets researched (company + person), cached once.</li>
            <li><b>Batches of 20–50</b> form automatically. First email is plain or HTML template; follow-ups always plain.</li>
            <li><b>Sending</b>: 1–5 min stagger per batch, per-agent daily cap, same-day dedupe across agents.</li>
            <li><b>Inbound replies</b> are handled by scenario-aware AI: objections, interest, demo requests — each gets a targeted response from the knowledge base.</li>
            <li><b>Pause anytime</b>: toggle stops new sends. Delete individual batches to skip them.</li>
          </ol>
        </div>
      )}

      {campaigns.length === 0 && <div className="card empty">No campaigns yet. Create one, then enroll leads from the Leads page.</div>}

      {campaigns.map(c => (
        <div key={c.id} className="card mb">
          <div className="row between">
            <div>
              <b style={{ fontSize: 15 }}>{c.name}</b>
              <div className="sm mut">
                Agent: {agentName(c.agent_id)} · {c.strategy} · {c.template_mode === 'template' ? 'Template' : 'Plain'} · batches of {c.batch_size}
                {c.target_country && ` · ${c.target_country}`}
              </div>
            </div>
            <div className="row">
              <span className={`pill ${c.status === 'active' ? 'ok' : 'gray'}`}>{c.status}</span>
              <div className={`switch ${c.status === 'active' ? 'on' : ''} ${aiDisabled ? 'disabled' : ''}`}
                   onClick={() => !aiDisabled && toggle(c)} role="button"
                   title={aiDisabled ? 'OpenAI API key required' : 'Pause / resume'}
                   style={aiDisabled ? { opacity: 0.45, cursor: 'not-allowed' } : undefined} />
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

      {/* ── Campaign drawer ── */}
      {form && (
        <div className="drawer-veil" onClick={e => e.target === e.currentTarget && setForm(null)}>
          <div className="drawer">

            {/* Step 0: preset picker */}
            {step === 0 && (
              <>
                <h2>New campaign — pick a starting point</h2>
                <p className="sm mut mb">Choose a preset and we'll fill in the strategy, tone, and goals for you. You can edit everything after.</p>
                <div style={{ display: 'grid', gap: 10, marginBottom: 18 }}>
                  {PRESETS.map((p, i) => (
                    <button key={i} className="btn ghost" style={{ textAlign: 'left', padding: '12px 16px', lineHeight: 1.5 }}
                      onClick={() => applyPreset(p)}>
                      <div style={{ fontWeight: 600 }}>{p.label}</div>
                      <div style={{ fontSize: 12, opacity: 0.6, marginTop: 2 }}>{p.hint}</div>
                    </button>
                  ))}
                </div>
                <div className="row">
                  <button className="btn ghost small" onClick={skipPreset}>Start from scratch →</button>
                  <button className="btn ghost" onClick={() => setForm(null)}>Cancel</button>
                </div>
              </>
            )}

            {/* Step 1: campaign form */}
            {step === 1 && (
              <>
                <div className="row between mb" style={{ marginBottom: 4 }}>
                  <h2 style={{ margin: 0 }}>New campaign</h2>
                  <button className="btn ghost small" onClick={() => setStep(0)}>← Change preset</button>
                </div>

                <div className="field">
                  <label>Campaign name <span style={{ color: '#e53e3e' }}>*</span></label>
                  <input value={form.name} onChange={e => set('name', e.target.value)}
                    placeholder="e.g. Q3 US SaaS — cold outreach" autoFocus />
                </div>

                <div className="field">
                  <label>Goal — what outcome are we driving?</label>
                  <textarea value={form.goal} onChange={e => set('goal', e.target.value)} rows={2}
                    placeholder="Book 30-min strategy calls with ops leaders..." />
                </div>

                <div className="grid c2">
                  <div className="field"><label>Agent <span style={{ color: '#e53e3e' }}>*</span></label>
                    <select value={form.agent_id} onChange={e => set('agent_id', e.target.value)}>
                      {agents.length === 0 && <option value="">— no agents yet —</option>}
                      {agents.map(a => <option key={a.id} value={a.id}>{a.name} — {a.role}</option>)}
                    </select>
                  </div>
                  <div className="field"><label>Strategy</label>
                    <select value={form.strategy} onChange={e => set('strategy', e.target.value)}>
                      {['B2B', 'B2C', 'ABM', 'custom'].map(s => <option key={s}>{s}</option>)}
                    </select>
                  </div>
                  <div className="field"><label>First email format</label>
                    <select value={form.template_mode} onChange={e => set('template_mode', e.target.value)}>
                      <option value="plain">Plain — simple professional text (recommended)</option>
                      <option value="template">Template — HTML with Chatversio logo</option>
                    </select>
                  </div>
                  <div className="field"><label>Email length</label>
                    <select value={form.email_length} onChange={e => set('email_length', e.target.value)}>
                      <option value="short">Short — 3–4 sentences, fast read</option>
                      <option value="concise">Concise — 5–7 sentences (default)</option>
                      <option value="professional">Professional — detailed & formal</option>
                      <option value="long">Long — full pitch with context</option>
                    </select>
                  </div>
                  <div className="field"><label>Batch size (20–50)</label>
                    <input type="number" min={20} max={50} value={form.batch_size}
                      onChange={e => set('batch_size', e.target.value)} />
                  </div>
                  <div className="field"><label>Target country <span className="sm mut">(optional)</span></label>
                    <input value={form.target_country} onChange={e => set('target_country', e.target.value)}
                      placeholder="UAE, United States, Germany…" />
                  </div>
                </div>

                <div className="field">
                  <label>Pain focus — what problem to anchor every email on</label>
                  <textarea value={form.target_focus} onChange={e => set('target_focus', e.target.value)} rows={2}
                    placeholder="e.g. manual customer support, leads leaving the website unanswered at night" />
                </div>

                <div className="field">
                  <label>What to pitch — be specific</label>
                  <textarea value={form.what_to_sell} onChange={e => set('what_to_sell', e.target.value)} rows={2}
                    placeholder="e.g. AI chat agents that qualify and book leads 24/7 without human involvement" />
                </div>

                <div className="field">
                  <label>What NOT to mention</label>
                  <textarea value={form.what_to_avoid} onChange={e => set('what_to_avoid', e.target.value)} rows={2}
                    placeholder="e.g. exact pricing, competitor names, aggressive CTAs" />
                </div>

                <p className="sm mut mb" style={{ marginTop: 0 }}>
                  Follow-ups and inbound replies are always plain text — format applies to first touch only.
                  Inbound objections (not interested, price, demo requests) are handled automatically by scenario-aware AI.
                </p>

                <div className="row">
                  <button className="btn" disabled={aiDisabled || !form.name.trim() || !form.agent_id}
                    onClick={create}
                    title={aiDisabled ? 'OpenAI API key required — configure in Super Admin' : undefined}>
                    {aiDisabled ? '🔑 Key required' : 'Create campaign'}
                  </button>
                  <button className="btn ghost" onClick={() => setForm(null)}>Cancel</button>
                </div>
              </>
            )}
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