import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import MiniOrb from '../MiniOrb.jsx'
import { Toast, useToast, useOpenAIKey } from '../App.jsx'
import Counter from '../Counter.jsx'
import { IconRocket, IconPlus, IconTrash } from '../Icons.jsx'

const STRATEGIES = [
  'B2B', 'B2C', 'C2C', 'C2B', 'B2G', 'G2C', 'B2B2C', 'B2B2B',
  'ABM', 'D2C', 'D2B', 'SMB', 'SME', 'Enterprise', 'custom',
]

// Smart presets — user picks one and fields auto-fill
const PRESETS = [
  {
    label: '🎯 B2B Cold Outreach',
    hint: 'Target businesses with a specific pain point',
    data: {
      strategy: 'B2B', template_mode: 'plain',
      email_length: 'concise', first_email_length: 'medium',
      followup_plan: '3,7,14', followup_count: 3,
      goal: 'Book discovery calls with decision-makers who have a specific operational pain',
      target_focus: 'manual processes, unanswered leads, slow customer support',
      what_to_sell: 'Chat agents and voice agents that talk to customers in realtime and hand over to a person when it matters',
      offering: 'Realtime chat and voice agents that talk to website visitors and hand over to a person when it matters',
      delivery_model: 'We build, host and train them per industry; they go live in about two weeks',
      ideal_customer: 'B2B companies whose sales or support team misses inbound conversations',
      what_to_avoid: 'exact pricing, competitor names, aggressive language',
    }
  },
  {
    label: '🏢 Enterprise ABM',
    hint: 'Named account targeting, high-touch messaging',
    data: {
      strategy: 'ABM', template_mode: 'template',
      email_length: 'professional', first_email_length: 'long',
      followup_plan: '5,12,21', followup_count: 3,
      goal: 'Open strategic conversations with C-suite and VP-level buyers at target accounts',
      target_focus: 'operational efficiency, cost reduction, competitive advantage',
      what_to_sell: 'Chat and voice agents handling customer conversations end to end in realtime',
      offering: 'Chat and voice agents that handle customer conversations end to end in realtime',
      delivery_model: 'Built, hosted and monitored by us; one named account owner per deployment',
      ideal_customer: 'Enterprise and upper-mid-market teams with an existing support or sales floor',
      what_to_avoid: 'pricing in first email, generic claims, anything that sounds mass-market',
    }
  },
  {
    label: '🚀 SaaS Trial Push',
    hint: 'Get product signups or live demos fast',
    data: {
      strategy: 'B2B', template_mode: 'plain',
      email_length: 'short', first_email_length: 'short',
      followup_plan: '1,3,7', followup_count: 3,
      goal: 'Get people onto a live realtime demo of the chat or voice agent',
      target_focus: 'inefficient current tools, time wasted on repetitive tasks',
      what_to_sell: 'A short live realtime demo — the agent actually talking to a customer, not a deck',
      offering: 'Realtime chat and voice agents that answer website visitors and book meetings',
      delivery_model: 'Built and hosted by us, trained on your own material, live in about two weeks',
      ideal_customer: 'SaaS teams whose trial signups and demo requests go unanswered',
      what_to_avoid: 'long explanations, multiple CTAs, pricing details',
    }
  },
  {
    label: '🌍 GCC / Middle East',
    hint: 'Region-specific tone for UAE, KSA, Qatar',
    data: {
      strategy: 'B2B', template_mode: 'template',
      email_length: 'professional', first_email_length: 'medium',
      followup_plan: '4,10,18', followup_count: 2,
      target_country: 'UAE',
      goal: 'Build trust and open a conversation — relationship first, pitch second',
      target_focus: 'digital transformation, customer experience, Vision 2030 alignment',
      what_to_sell: 'Chat and voice agents that handle customer conversations in realtime, in Arabic and English',
      offering: 'Chat and voice agents handling customer conversations in realtime, in Arabic and English',
      delivery_model: 'Built, hosted and supported in the region, live in about two weeks, Arabic-first where you need it',
      ideal_customer: 'Enterprises and public-facing teams in the UAE, KSA and Qatar going digital',
      what_to_avoid: 'overly pushy tone, aggressive CTAs, Western-centric language',
    }
  },
]

const ALL_DAYS = [
  ['mon', 'Mon'], ['tue', 'Tue'], ['wed', 'Wed'], ['thu', 'Thu'],
  ['fri', 'Fri'], ['sat', 'Sat'], ['sun', 'Sun'],
]

// Every part starts ticked: the campaign uses the whole agent as configured.
const ALL_PART_KEYS = [
  'what_you_sell', 'ideal_customer', 'avoid_phrases', 'platform_rules',
  'extra_instructions', 'no_pricing', 'cta', 'excluded_titles', 'target_titles',
  'unsubscribe', 'subject', 'body', 'followups', 'not_interested', 'interested',
]
const DEFAULT_PARTS = [...ALL_PART_KEYS]

const BLANK = {
  name: '', goal: '', strategy: 'B2B', strategy_notes: '', template_mode: 'plain',
  email_length: 'concise', what_to_sell: '', what_to_avoid: '',
  target_focus: '', target_country: '',
  followup_1_hours: 24, followup_2_hours: 48, followup_3_hours: 72, followup_max_days: 7,
  // Days-wise + count-wise follow-up plan. Leave the plan blank to keep the
  // legacy hour-based stage timing; fill it in and this wins instead.
  followup_plan: '3,7,14',
  followup_count: 3,
  followup_memory: true,
  // FOLLOW-UP SCHEDULE — which days of the week and at what time (UTC).
  // [] / '' means any day, any time — the behaviour every older campaign has.
  followup_days: [],
  followup_time: '',
  // "Not interested" -> the agent never replies, the lead parks in Trash and
  // is deleted after the retention window. Set to 'close' to close instead.
  not_interested_action: 'garbage',
  not_interested_retention_days: 30,
  // The AI never answers price / contract / legal / security questions.
  pricing_policy: 'escalate',
  // First email length, and whether we offer a live realtime demo.
  first_email_length: 'medium',
  demo_offer: true,
  subject_max_words: 3,
  // ── WHAT ARE YOU OFFERING? ────────────────────────────────────────────────
  // Reality-based description of the service + how it is delivered, in plain
  // text. Never a pitch — this is what the agent works from.
  offering: '',
  delivery_model: '',
  // Who the email is actually for, and any platform rules of your own.
  ideal_customer: '',
  platform_rules: '',
  // Part-level switches that mirror the selection box below. Every one is on
  // by default — that is the default Agent prompt too.
  no_pricing: true,
  cta_enabled: true,
  booking_link: '',
  // SELECTION BOX — which parts of the agent this campaign drives.
  agent_parts: [...DEFAULT_PARTS],
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
  const [parts, setParts] = useState([])      // selection-box definitions
  const [form, setForm] = useState(null)
  const [editingId, setEditingId] = useState(null)
  const [showHow, setShowHow] = useState(false)
  const [step, setStep] = useState(0) // 0=preset picker, 1=form
  const [toast, show] = useToast()

  const load = async () => {
    const [cp, ags] = await Promise.all([api.campaignsPaged({ page, per_page: perPage }), api.agents()])
    setCampaigns(cp.items); setTotal(cp.total); setPages(cp.pages)
    setAgents(ags)
  }
  useEffect(() => { load().catch(e => show(e.message, true)) }, [page])
  useEffect(() => { const t = setInterval(() => load().catch(() => {}), 15000); return () => clearInterval(t) }, [page])
  useEffect(() => { api.campaignParts().then(d => setParts(d.parts || [])).catch(() => {}) }, [])

  const openNew = () => {
    setStep(0)
    setEditingId(null)
    setForm({ ...BLANK, agent_parts: [...DEFAULT_PARTS], agent_id: agents[0]?.id || '' })
  }

  const openEdit = (c) => {
    setEditingId(c.id)
    setStep(1)
    setForm({
      ...BLANK, ...c,
      // strings from the API back into the arrays the form edits
      followup_days: (c.followup_days || '').split(',').filter(Boolean),
      agent_parts: (c.agent_parts
        ? c.agent_parts.split(',').filter(Boolean)
        : [...DEFAULT_PART_KEYS]),
      agent_id: c.agent_id || '',
    })
  }

  const applyPreset = (preset) => {
    setForm(f => ({ ...f, ...preset.data }))
    setStep(1)
  }

  const skipPreset = () => setStep(1)

  const save = async () => {
    if (!form.name.trim()) { show('Campaign name is required', true); return }
    if (!form.agent_id) { show('Please select an agent', true); return }
    if (!(form.agent_parts || []).length) { show('Select at least one part of the agent', true); return }
    const payload = {
      ...form,
      agent_id: +form.agent_id,
      // the form edits arrays; the API stores comma lists
      followup_days: (form.followup_days || []).join(','),
      agent_parts: (form.agent_parts || []).join(','),
    }
    try {
      if (editingId) await api.updateCampaign(editingId, payload)
      else await api.createCampaign(payload)
      setForm(null); setStep(0); setEditingId(null); load()
      show(editingId ? 'Campaign updated ✓' : 'Campaign created ✓')
    } catch (e) { show(e.message, true) }
  }

  const toggle = async (c) => { await api.toggleCampaign(c.id); load() }
  const delCampaign = async (c) => {
    if (!confirm(`Delete campaign "${c.name}"?`)) return
    await api.deleteCampaign(c.id); load(); show('Campaign deleted')
  }

  const agentName = id => agents.find(a => a.id === id)?.name || '—'
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  // SELECTION BOX — one tick per part of the agent this campaign may drive.
  // Keeping the canonical order means what you see is what the prompt builder
  // walks through.
  const togglePart = (k) => setForm(f => {
    const cur = new Set(f.agent_parts || [])
    if (cur.has(k)) cur.delete(k); else cur.add(k)
    if (!cur.size) cur.add(k)          // never allow an empty selection
    return { ...f, agent_parts: ALL_PART_KEYS.filter(x => cur.has(x)) }
  })
  const toggleDay = (d) => setForm(f => {
    const cur = f.followup_days || []
    const next = cur.includes(d) ? cur.filter(x => x !== d) : [...cur, d]
    return { ...f, followup_days: ALL_DAYS.map(([k]) => k).filter(k => next.includes(k)) }
  })

  const partOn = (k) => !!form && (form.agent_parts || []).includes(k)
  const partsOk = !!form && (form.agent_parts || []).length > 0
  const allPartsOn = !!form && (form.agent_parts || []).length === ALL_PART_KEYS.length

  const totalActive = campaigns.filter(c => c.status === 'active').length

  return (
    <>
      <div className="records-intro card mb">
        <MiniOrb size={52} color="#d97706" accent="#0054FC" />
        <div style={{ flex: 1 }}>
          <b>Campaigns — <Counter value={totalActive} /> active</b>
          <p className="sm mut mt">
            Each campaign tells one agent how to sell: target country, pain focus, what to pitch,
            what to avoid. Emails send one at a time in order (FIFO) so inboxes stay healthy.
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
            <li><b>FIFO sending</b> — emails go out one at a time in the order selected, each spaced by the agent's outbound delay. Batching happens behind the scenes - the card below only shows how many leads were sent; per-batch detail lives in Mail Records. Per-agent daily cap + same-day across-agent dedupe still apply.</li>
            <li><b>Inbound replies</b> are handled by scenario-aware AI: objections, interest, demo requests — each gets a targeted response from the knowledge base.</li>
            <li><b>Auto-close</b> — no-reply sequences and declines move to Trash automatically; no agent ever emails a closed lead again unless it writes back.</li>
            <li><b>Pause anytime</b> — the toggle stops new sends.</li>
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
                Agent: {agentName(c.agent_id)} · {c.strategy} · {c.template_mode === 'template' ? 'Template' : 'Plain'}
                {c.target_country && ` · ${c.target_country}`}
                {c.followup_plan
                  ? ` · follow-ups day ${c.followup_plan.replace(/,/g, ' / ')} (max ${c.followup_count ?? 0})`
                  : (c.followup_1_hours ? ` · follow-ups ${c.followup_1_hours}h / ${c.followup_2_hours}h / ${c.followup_3_hours}h` : '')}
                {c.followup_max_days ? ` · auto-close after ${c.followup_max_days}d → Trash` : ''}
                {c.demo_offer !== false ? ' · realtime demo offer' : ' · no demo offer'}
                {c.pricing_policy === 'escalate' ? ' · price/legal → human' : ''}
              </div>
            </div>
            <div className="row">
              <span className={`pill ${c.status === 'active' ? 'ok' : 'gray'}`}>{c.status}</span>
              <div className={`switch ${c.status === 'active' ? 'on' : ''} ${aiDisabled ? 'disabled' : ''}`}
                   onClick={() => !aiDisabled && toggle(c)} role="button"
                   title={aiDisabled ? 'OpenAI API key required' : 'Pause / resume'}
                   style={aiDisabled ? { opacity: 0.45, cursor: 'not-allowed' } : undefined} />
              <button className="btn ghost small" onClick={() => openEdit(c)}>Edit</button>
              <button className="btn danger small" onClick={() => delCampaign(c)}>Delete</button>
            </div>
          </div>
          {c.goal && <p className="sm mut mt">{c.goal}</p>}
          {(c.offering || c.delivery_model) && (
            <p className="sm mut" style={{ margin: '6px 0 0' }}>
              {c.offering && <><b>Offering:</b> {c.offering}<br /></>}
              {c.delivery_model && <><b>Delivery:</b> {c.delivery_model}</>}
            </p>
          )}
          <div className="sm mut mt">
            {c.followup_days
              ? `follow-ups only on ${c.followup_days.split(',').map(d => d[0].toUpperCase() + d.slice(1)).join(', ')}`
              : 'follow-ups any day'}
            {c.followup_time ? ` at ${c.followup_time} UTC` : ' at any time'}
            {' · '}
            {c.agent_parts
              ? `${c.agent_parts.split(',').length} of 15 agent parts driven by this campaign`
              : 'drives every part of the agent'}
          </div>
          <div className="row wrap sm mt" style={{ gap: 14 }}>
            <span>
              <b style={{ color: 'var(--blue)' }}><Counter value={c.leads_enrolled || 0} /></b>{' '}
              leads enrolled
            </span>
            <span>
              <b style={{ color: 'var(--blue)' }}><Counter value={c.outbound_sent || 0} /></b>{' '}
              emails sent
            </span>
            <span>
              <b><Counter value={c.replies_received || 0} /></b> replies
            </span>
            <span>
              <b><Counter value={c.followups_sent || 0} /></b> follow-ups
            </span>
            {c.escalated > 0 && (
              <span className="pill hot" title="Meeting links, promotions, role-account replies, delivery failures and blocked sends — see the Escalation page">
                <Counter value={c.escalated} /> escalated
              </span>
            )}
            <span className="mut" style={{ marginLeft: 'auto' }}>
              {c.status === 'active' ? 'sending automatically (FIFO)' : 'paused'} · batch detail in Mail Records
            </span>
          </div>
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
                  <h2 style={{ margin: 0 }}>{editingId ? 'Edit campaign' : 'New campaign'}</h2>
                  {!editingId && <button className="btn ghost small" onClick={() => setStep(0)}>← Change preset</button>}
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

                <div className="card mb" style={{ padding: 14, background: 'rgba(217,119,6,0.05)' }}>
                  <b style={{ fontSize: 13 }}>What are you offering?</b>
                  <p className="sm mut" style={{ margin: '4px 0 10px' }}>
                    Say it the way it actually is — plain, reality-based description of the work.
                    Not a pitch, not a benefit list. This is what the agent works from.
                  </p>
                  <div className="field">
                    <label>The offering</label>
                    <textarea value={form.offering} onChange={e => set('offering', e.target.value)} rows={2}
                      placeholder="e.g. We build realtime chat agents that answer website visitors and hand over to a person when it matters" />
                  </div>
                  <div className="field" style={{ marginBottom: 0 }}>
                    <label>Delivery model <span className="sm mut">(plain text — what the client actually gets, and how)</span></label>
                    <textarea value={form.delivery_model} onChange={e => set('delivery_model', e.target.value)} rows={2}
                      placeholder="e.g. We build, host and train them per industry; they go live in about two weeks" />
                  </div>
                </div>

                <div className="field">
                  <label>Ideal customer profile <span className="sm mut">(who this is written for)</span></label>
                  <textarea value={form.ideal_customer} onChange={e => set('ideal_customer', e.target.value)} rows={2}
                    placeholder="e.g. B2B companies whose sales or support team misses inbound conversations" />
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
                      {STRATEGIES.map(s => <option key={s}>{s}</option>)}
                    </select>
                  </div>
                  <div className="field"><label>Strategy note <span className="sm mut">(optional info)</span></label>
                    <textarea value={form.strategy_notes} onChange={e => set('strategy_notes', e.target.value)} rows={2}
                      placeholder="e.g. C2C — consumer-to-consumer, keep it friendly and personal" />
                  </div>
                  <div className="field"><label>First email format</label>
                    <select value={form.template_mode} onChange={e => set('template_mode', e.target.value)}>
                      <option value="plain">Plain — simple professional text (recommended)</option>
                      <option value="template">Template — HTML with Chatversio logo</option>
                    </select>
                  </div>
                  <div className="field"><label>First email length</label>
                    <select value={form.first_email_length || 'medium'}
                      onChange={e => set('first_email_length', e.target.value)}>
                      <option value="short">Short — 3–4 sentences</option>
                      <option value="medium">Medium — 5–7 sentences (default)</option>
                      <option value="long">Long — up to 3 short paragraphs</option>
                    </select>
                  </div>
                  <div className="field"><label>Reply length</label>
                    <select value={form.email_length} onChange={e => set('email_length', e.target.value)}>
                      <option value="short">Short — 3–5 sentences, fast read</option>
                      <option value="concise">Concise — 5–7 sentences (default)</option>
                      <option value="professional">Professional — detailed & formal</option>
                      <option value="long">Long — full context</option>
                    </select>
                  </div>
                  <div className="field"><label>Subject line</label>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <input type="number" min={1} max={8} style={{ width: 90 }}
                        value={form.subject_max_words ?? 3}
                        onChange={e => set('subject_max_words', +e.target.value)} />
                      <span className="sm mut">words max — always written by the system, never by the model</span>
                    </div>
                  </div>
                  <div className="field"><label>Target country <span className="sm mut">(optional)</span></label>
                    <input value={form.target_country} onChange={e => set('target_country', e.target.value)}
                      placeholder="UAE, United States, Germany…" />
                  </div>
                </div>

                <div className="card mb" style={{ padding: 14 }}>
                  <b style={{ fontSize: 13 }}>Pricing &amp; call to action</b>
                  <label style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
                    <input type="checkbox" style={{ width: 'auto' }} checked={form.no_pricing !== false}
                      onChange={e => set('no_pricing', e.target.checked)} />
                    <span>No pricing talk
                      <span className="sm mut"> — never price, cost, fees, quotes, discounts, budgets, packages or currency amounts, subject or body, first email or follow-up. If they ask, a colleague comes back with the details.</span></span>
                  </label>
                  <label style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
                    <input type="checkbox" style={{ width: 'auto' }} checked={form.cta_enabled !== false}
                      onChange={e => set('cta_enabled', e.target.checked)} />
                    <span>End on the booking link
                      <span className="sm mut"> — the call to action is a calendar link, and it is the one URL the system will insert.</span></span>
                  </label>
                  <div className="field" style={{ marginTop: 8, marginBottom: 0 }}>
                    <label>Booking link <span className="sm mut">(leave empty to use the agent's meeting URL)</span></label>
                    <input value={form.booking_link} onChange={e => set('booking_link', e.target.value)}
                      placeholder="https://calendly.com/…" />
                  </div>
                </div>

                <div className="field">
                  <label>Follow-up plan — days after the last email</label>
                  <div className="grid c2" style={{ marginTop: 6 }}>
                    <div className="field"><label>Plan (days, comma separated)</label>
                      <input value={form.followup_plan || ''} onChange={e => set('followup_plan', e.target.value)}
                        placeholder="3,7,14" />
                    </div>
                    <div className="field"><label>How many follow-ups max</label>
                      <input type="number" min={0} max={20} value={form.followup_count ?? 3}
                        onChange={e => set('followup_count', +e.target.value)} />
                    </div>
                  </div>
                  <label style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
                    <input type="checkbox" style={{ width: 'auto' }} checked={form.followup_memory !== false}
                      onChange={e => set('followup_memory', e.target.checked)} />
                    <span>Follow-ups read the real conversation and build on it
                      <span className="sm mut"> — off means a generic standalone nudge</span></span>
                  </label>
                  <p className="sm mut" style={{ margin: '4px 0 0' }}>
                    A plan of <code>3,7,14</code> means the 1st follow-up goes 3 days after the last
                    email, the 2nd 7 days after that, the 3rd 14 days after that — and the count
                    above caps how many actually go out. Clear the plan to fall back to hour-based
                    timing.
                  </p>

                  <div className="grid c2" style={{ marginTop: 14 }}>
                    <div className="field" style={{ marginBottom: 0 }}>
                      <label>Which days a follow-up may go out</label>
                      <div className="row" style={{ gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
                        {ALL_DAYS.map(([k, lbl]) => (
                          <label key={k} className="sm" style={{
                            display: 'inline-flex', gap: 5, alignItems: 'center',
                            border: '1px solid var(--line)', borderRadius: 8,
                            padding: '5px 9px', cursor: 'pointer',
                            background: form.followup_days?.includes(k) ? 'rgba(0,84,252,0.10)' : 'transparent',
                          }}>
                            <input type="checkbox" style={{ width: 'auto', margin: 0 }}
                              checked={form.followup_days?.includes(k) || false}
                              onChange={() => toggleDay(k)} />
                            {lbl}
                          </label>
                        ))}
                      </div>
                      <p className="sm mut" style={{ margin: '6px 0 0' }}>
                        Nothing ticked = every day, exactly as before.
                      </p>
                    </div>
                    <div className="field" style={{ marginBottom: 0 }}>
                      <label>Time of day <span className="sm mut">(UTC)</span></label>
                      <input type="time" value={form.followup_time || ''}
                        onChange={e => set('followup_time', e.target.value)} />
                      <p className="sm mut" style={{ margin: '6px 0 0' }}>
                        Empty = any time. Used by the follow-up scheduler together with the days above.
                      </p>
                    </div>
                  </div>
                </div>

                <div className="field">
                  <label>Auto-close & "not interested"</label>
                  <div className="grid c2" style={{ marginTop: 6 }}>
                    <div className="field"><label>Close & move to Trash after (days)</label>
                      <input type="number" min={1} max={365} value={form.followup_max_days}
                        onChange={e => set('followup_max_days', +e.target.value)} />
                    </div>
                    <div className="field"><label>When they say "not interested"</label>
                      <select value={form.not_interested_action || 'garbage'}
                        onChange={e => set('not_interested_action', e.target.value)}>
                        <option value="garbage">No reply at all — park in Trash, then delete</option>
                        <option value="close">No reply at all — just close the thread</option>
                      </select>
                    </div>
                    <div className="field"><label>Delete it after (days)</label>
                      <input type="number" min={0} max={3650}
                        value={form.not_interested_retention_days ?? 30}
                        onChange={e => set('not_interested_retention_days', +e.target.value)} />
                    </div>
                    <div className="field"><label>Price / contract / legal questions</label>
                      <select value={form.pricing_policy || 'escalate'}
                        onChange={e => set('pricing_policy', e.target.value)}>
                        <option value="escalate">Never answer — pause the agent, ask a human</option>
                        <option value="reply">Let the agent reply itself</option>
                      </select>
                    </div>
                  </div>
                  <label style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
                    <input type="checkbox" style={{ width: 'auto' }} checked={form.demo_offer !== false}
                      onChange={e => set('demo_offer', e.target.checked)} />
                    <span>Offer a live realtime demo <span className="sm mut">— not a brochure or a deck</span></span>
                  </label>
                  <p className="sm mut" style={{ margin: '4px 0 0' }}>
                    If someone says they are not interested or do not want to work, the agent
                    sends <b>nothing at all</b> and goes silent on that thread. The lead waits in
                    Trash so you can still see it, then is deleted for good after the retention
                    window. If they ask about pricing, a quote, a contract, legal, security or
                    who the company is, the agent never answers — it pauses, flags it on the
                    Escalation page, and the conversation stays in Messages for you to reply to.
                  </p>
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

                <div className="field">
                  <label>Platform rules <span className="sm mut">(leave empty to use the built-in rules)</span></label>
                  <textarea value={form.platform_rules} onChange={e => set('platform_rules', e.target.value)} rows={2}
                    placeholder="e.g. no links in the first email; Gmail and Outlook limits; plain text only" />
                </div>

                {/* ── SELECTION BOX: which parts of the agent this campaign drives ── */}
                <div className="card mb" style={{ padding: 14, background: 'rgba(0,84,252,0.045)' }}>
                  <div className="row between" style={{ alignItems: 'flex-start' }}>
                    <div>
                      <b style={{ fontSize: 13 }}>Which parts of the agent does this campaign drive?</b>
                      <p className="sm mut" style={{ margin: '4px 0 0' }}>
                        Every part is ticked by default, which is exactly what the default Agent prompt
                        says. Untick anything this campaign must not touch — it then falls back to the
                        agent as configured, untouched.
                      </p>
                    </div>
                    <span className={`pill ${allPartsOn ? 'ok' : 'gray'}`}>
                      {form.agent_parts?.length || 0} / {ALL_PART_KEYS.length} parts
                    </span>
                  </div>

                  <div className="grid c2" style={{ marginTop: 12 }}>
                    {(parts.length ? parts : ALL_PART_KEYS.map(k => ({ key: k, label: k, desc: '' }))).map(p => (
                      <label key={p.key} style={{
                        display: 'flex', gap: 8, alignItems: 'flex-start',
                        border: '1px solid var(--line)', borderRadius: 10,
                        padding: '9px 11px', cursor: 'pointer',
                        background: partOn(p.key) ? 'rgba(0,84,252,0.06)' : 'transparent',
                        opacity: partOn(p.key) ? 1 : 0.65,
                      }}>
                        <input type="checkbox" style={{ width: 'auto', marginTop: 2 }}
                          checked={partOn(p.key)} onChange={() => togglePart(p.key)} />
                        <span>
                          <b style={{ fontSize: 12.5 }}>{p.label}</b>
                          <span className="sm mut" style={{ display: 'block' }}>{p.desc}</span>
                          {p.rule && <span className="sm mut" style={{ display: 'block', opacity: 0.75 }}>{p.rule}</span>}
                        </span>
                      </label>
                    ))}
                  </div>

                  <div className="sm mut mt" style={{ display: 'grid', gap: 3 }}>
                    <span>
                      <b style={{ color: 'var(--blue)' }}>Not interested</b> → lead goes Cold, the
                      conversation stays in <b>Messages</b>, the lead moves to <b>Trash</b>.
                    </span>
                    <span>
                      <b style={{ color: 'var(--blue)' }}>Interested</b> → lead goes Hot, conversation
                      stays in <b>Messages</b>.
                    </span>
                    <span>
                      <b style={{ color: 'var(--blue)' }}>Subject</b> → 3 words maximum, written by the
                      system, never by the model.
                    </span>
                    <span>
                      <b style={{ color: 'var(--blue)' }}>Unsubscribe</b> → untick it to add a plain-text
                      opt-out line. Ticked (default) = no opt-out line and no <code>List-Unsubscribe</code>.
                    </span>
                  </div>
                </div>

                <p className="sm mut mb" style={{ marginTop: 0 }}>
                  Follow-ups and inbound replies are always plain text — format applies to first touch only.
                  Inbound objections (not interested, price, demo requests) are handled automatically by scenario-aware AI.
                </p>

                <div className="row">
                  <button className="btn" disabled={aiDisabled || !form.name.trim() || !form.agent_id || !partsOk}
                    onClick={save}
                    title={aiDisabled ? 'OpenAI API key required — configure in Super Admin' : undefined}>
                    {aiDisabled ? '🔑 Key required' : (editingId ? 'Save campaign' : 'Create campaign')}
                  </button>
                  <button className="btn ghost" onClick={() => { setForm(null); setEditingId(null) }}>Cancel</button>
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