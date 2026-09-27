import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Toast, useToast } from '../App.jsx'

const BLANK = { name: '', role: '', description: '', persona_prompt: '', pitch_style: '',
  sentiment_prompt: '', country_prompt: '', judgment_prompt: '',
  persona: '', why_you: '', target_titles: '', target_location: '',
  excluded_titles: '', excluded_companies: '', solutions: '', avoid_phrases: '',
  extra_instructions: '',
  tone: 'professional', message_length: 'medium', project_url: '', meeting_url: '',
  signature: '', daily_send_limit: 150, outbound_delay_min: 180, outbound_delay_max: 720,
  reply_delay_seconds: 900, avatar_url: '',
  smtp_host: '', smtp_port: 587, smtp_user: '', smtp_password: '', smtp_from: '',
  imap_host: '', imap_port: 993, imap_user: '', imap_password: '' }

// Fields that are only ever added by the backend — an agent fetched before
// the column existed still has to render as a controlled input.
const FILL = ['persona', 'why_you', 'target_titles', 'target_location',
  'excluded_titles', 'excluded_companies', 'solutions', 'avoid_phrases',
  'extra_instructions']

const splitList = (s) => (s || '').split(/[,\n;|]+/).map(x => x.trim()).filter(Boolean)

// The four voices the product ships with — used if /api/agents/playbook is
// unreachable, so the picker never comes up empty.
const PERSONA_FALLBACK = [
  { id: 'osaja', name: 'Osaja', voice: 'Consultative, calm, curious.' },
  { id: 'saif', name: 'Saif', voice: 'Founder to founder. Short and direct.' },
  { id: 'aleem', name: 'Aleem', voice: 'Technical peer. Specific, no buzzwords.' },
  { id: 'dawood', name: 'Dawood', voice: 'Solo developer. Personal, proof-driven.' },
]

export default function Agents() {
  const [agents, setAgents] = useState([])
  const [book, setBook] = useState(null)   // solutions / personas / banned words
  const [defPrompt, setDefPrompt] = useState('')  // the default agent prompt
  const [showPrompt, setShowPrompt] = useState(false)
  const [edit, setEdit] = useState(null)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [toast, show] = useToast()

  const load = () => api.agents().then(setAgents).catch(e => show(e.message, true))
  useEffect(() => { load() }, [])
  useEffect(() => { api.agentPlaybook().then(setBook).catch(() => {}) }, [])
  useEffect(() => {
    if (!showPrompt || defPrompt) return
    api.defaultPrompt().then(d => setDefPrompt(d.prompt || '')).catch(() => {})
  }, [showPrompt, defPrompt])

  const openEditor = (a) => {
    const base = { ...BLANK, ...a }
    FILL.forEach(k => { if (base[k] === undefined || base[k] === null) base[k] = BLANK[k] })
    setEdit(base)
  }

  // Solutions the agent may present. Empty field = the whole catalogue.
  const solutionOn = (id) => {
    const picked = splitList(edit?.solutions).map(s => s.toLowerCase())
    return picked.length === 0 || picked.includes(id)
  }
  const toggleSolution = (id) => {
    const all = (book?.solutions || []).map(s => s.id)
    let picked = splitList(edit.solutions).map(s => s.toLowerCase())
    if (picked.length === 0) picked = [...all]        // first untick starts from "all"
    picked = picked.includes(id) ? picked.filter(x => x !== id) : [...picked, id]
    const full = picked.length === all.length && all.every(x => picked.includes(x))
    set('solutions', full ? '' : picked.join(', '))
  }

  const toggle = async (a) => {
    const r = await api.toggleAgent(a.id)
    setAgents(list => list.map(x => x.id === a.id ? { ...x, is_active: r.is_active } : x))
    show(`${a.name} ${r.is_active ? 'is live' : 'paused'}`)
  }

  const testConnection = async () => {
    setTesting(true); setTestResult(null)
    try {
      const r = await api.testMailboxConnection(edit)
      setTestResult(r)
      show(r.smtp.ok && r.imap.ok ? 'Both SMTP and IMAP work — safe to save' : 'See details below', !(r.smtp.ok && r.imap.ok))
    } catch (e) { show(e.message, true) } finally { setTesting(false) }
  }

  const save = async () => {
  try { await api.saveAgent(edit, edit.id); setEdit(null); setTestResult(null); load(); show('Agent saved') }
  catch (e) { show(e.message, true) }
}

  const del = async (a) => {
    if (!window.confirm(`Delete agent "${a.name}"? This cannot be undone.`)) return
    try {
      await api.deleteAgent(a.id)
      load()
      show(`${a.name} deleted`)
    } catch (e) { show(e.message, true) }
  }
  const set = (k, v) => setEdit(ed => ({ ...ed, [k]: v }))

  return (
    <>
      <div className="grid c2">
        {agents.map(a => (
          <div key={a.id} className="card agent-card">
            <div className="agent-card-head">
              <img
                src={`/${a.name.toLowerCase()}.png`}
                alt={a.name}
                className="agent-photo-lg"
                onError={(e) => { e.target.style.display = 'none' }}
              />
              <div style={{ flex: 1 }}>
                <div className="row between">
                  <div>
                    <b style={{ fontSize: 17, color: 'var(--navy)' }}>{a.name}</b>
                    <div className="sm mut">{a.role}</div>
                  </div>
                  <div className="row" style={{ gap: 8 }}>
                    <span className="sm mut">{a.is_active ? 'Live' : 'Paused'}</span>
                    <div className={`switch ${a.is_active ? 'on' : ''}`} onClick={() => toggle(a)}
                         role="button" title="Play / pause this agent" />
                  </div>
                </div>
              </div>
            </div>
            <p className="sm mut mt">{a.description}</p>
            <div className="row wrap mt sm">
              <span className="pill blue">{a.persona || a.tone}</span>
              <span className="pill gray">{a.message_length}</span>
              <span className="pill gray" title="This agent's own daily cap. The Settings page cap is a ceiling: whichever number is LOWER is what actually applies.">
                {a.daily_send_limit}/day max
              </span>
              <span className="pill gray">out {Math.round(a.outbound_delay_min / 60)}–{Math.round(a.outbound_delay_max / 60)}m</span>
              <span className="pill gray">reply ~{Math.round(a.reply_delay_seconds / 60)}m</span>
              <span className={`pill ${a.smtp_configured ? 'ok' : 'gray'}`}>
                {a.smtp_configured ? `✉ ${a.smtp_user}` : 'no mailbox'}
              </span>
              {splitList(a.target_titles).length > 0 && (
                <span className="pill blue" title={`Targets these roles:\n${splitList(a.target_titles).join(', ')}`}>
                  → {splitList(a.target_titles).length} target titles
                </span>
              )}
              {a.target_location && <span className="pill gray" title="Market this agent writes for">📍 {a.target_location}</span>}
              {(splitList(a.excluded_titles).length > 0 || splitList(a.excluded_companies).length > 0) && (
                <span className="pill hot" title={[...splitList(a.excluded_titles), ...splitList(a.excluded_companies)].join(', ')}>
                  ✕ {splitList(a.excluded_titles).length + splitList(a.excluded_companies).length} excluded
                </span>
              )}
              {splitList(a.avoid_phrases).length > 0 && (
                <span className="pill gray" title={splitList(a.avoid_phrases).join(', ')}>
                  ∅ {splitList(a.avoid_phrases).length} banned phrases
                </span>
              )}
            </div>
            <div className="row mt">
            <button className="btn ghost small" onClick={() => openEditor(a)}>Configure</button>
            <button className="btn ghost small" style={{ color: 'var(--hot)' }} onClick={() => del(a)}>Delete</button>
          </div>
          </div>
        ))}
      </div>

      <div className="card mb" style={{ marginTop: 14 }}>
        <div className="row between">
          <div style={{ flex: 1, marginRight: 12 }}>
            <b>Default agent prompt</b>
            <p className="sm mut" style={{ margin: '4px 0 0' }}>
              What every agent runs by: what you sell, ideal customer, avoid phrases, platform
              rules, extra instructions, no pricing talk, CTA, excluded / target titles,
              unsubscribe, subject, body, follow-ups, not-interested and interested handling.
              A campaign's selection box narrows this down to the parts that campaign drives —
              everything ticked (the default) means the whole prompt above.
            </p>
          </div>
          <button className="btn ghost small" onClick={() => { setDefPrompt(''); setShowPrompt(s => !s) }}>
            {showPrompt ? 'Hide prompt' : 'Show prompt'}
          </button>
        </div>
        {showPrompt && (
          <pre style={{
            whiteSpace: 'pre-wrap', fontSize: 11.5, lineHeight: 1.55,
            background: 'rgba(0,0,0,0.35)', borderRadius: 10, padding: 12,
            marginTop: 10, maxHeight: 440, overflow: 'auto',
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
          }}>{defPrompt || '…'}</pre>
        )}
      </div>

      {agents.length < 10 && (
        <button className="btn mt" onClick={() => setEdit({ ...BLANK })}>+ New agent</button>
      )}

      {edit && (
        <div className="drawer-veil" onClick={e => e.target === e.currentTarget && setEdit(null)}>
          <div className="drawer">
            <h2>{edit.id ? `Configure ${edit.name}` : 'New agent'}</h2>
            <div className="grid c2">
              <div className="field"><label>Name</label>
                <input value={edit.name} onChange={e => set('name', e.target.value)} /></div>
              <div className="field"><label>Role</label>
                <input value={edit.role} onChange={e => set('role', e.target.value)} placeholder="Senior Sales Strategist" /></div>
            </div>
            <div className="field"><label>Description</label>
              <textarea value={edit.description} onChange={e => set('description', e.target.value)} /></div>

            {/* ── WHO / WHAT / HOW ─ read by the prompt AND enforced in code ── */}
            <h2 style={{ marginTop: 14 }}>Voice &amp; targeting</h2>
            <div className="grid c2">
              <div className="field">
                <label>Persona — who this agent writes as</label>
                <select value={edit.persona} onChange={e => set('persona', e.target.value)}>
                  <option value="">— match the agent name —</option>
                  {(book?.personas || PERSONA_FALLBACK).map(p => (
                    <option key={p.id} value={p.id}>{p.name} — {p.voice}</option>
                  ))}
                </select>
                <p className="sm mut" style={{ margin: '4px 0 0' }}>
                  Chooses the built-in voice, so it changes how the agent writes,
                  replies and pitches — not just what it is called.
                </p>
              </div>
              <div className="field">
                <label>Target location / market <span className="sm mut">(optional)</span></label>
                <input value={edit.target_location} onChange={e => set('target_location', e.target.value)}
                  placeholder="United States, UAE, Germany, United Kingdom…" />
                <p className="sm mut" style={{ margin: '4px 0 0' }}>
                  Tone, formality, references and business etiquette are written for
                  this market. Leads whose country is known and falls outside it are
                  skipped. Blank = follow each lead's own country.
                </p>
              </div>
            </div>

            <div className="field">
              <label>Target titles — the roles this agent communicates with</label>
              <textarea rows={2} value={edit.target_titles} onChange={e => set('target_titles', e.target.value)}
                placeholder="founder, ceo, cto, head of support, operations manager…" />
              <p className="sm mut" style={{ margin: '4px 0 0' }}>
                The agent writes to these roles and to what they own. A lead with a
                known title outside this list is not enrolled and never emailed.
                Blank titles are never filtered. Comma or newline separated.
              </p>
            </div>

            <div className="grid c2">
              <div className="field">
                <label>Never contact — excluded job titles</label>
                <textarea rows={2} value={edit.excluded_titles}
                  onChange={e => set('excluded_titles', e.target.value)}
                  placeholder="recruiter, intern, student, freelancer…" />
                <p className="sm mut" style={{ margin: '4px 0 0' }}>
                  Hard rule: no opening email, no follow-up, no reply — inbound or
                  outbound. Checked in code before anything is generated.
                </p>
              </div>
              <div className="field">
                <label>Never contact — companies / company types</label>
                <textarea rows={2} value={edit.excluded_companies}
                  onChange={e => set('excluded_companies', e.target.value)}
                  placeholder="named accounts, competitors, agencies, enterprises…" />
                <p className="sm mut" style={{ margin: '4px 0 0' }}>
                  Matched on company name, website domain and email domain, so a
                  list of high-value accounts and a whole company type work the
                  same way.
                </p>
              </div>
            </div>

            <div className="field">
              <label>Why you? — what this agent brings (value, proof, outcomes)</label>
              <textarea rows={3} value={edit.why_you} onChange={e => set('why_you', e.target.value)}
                placeholder="What has actually been observed: the outcome, the proof, the business result. Never an offer, never a benefit list." />
              <p className="sm mut" style={{ margin: '4px 0 0' }}>
                Goes into the prompt as facts about the work — value, proof and the
                result it produced — never as something being sold.
              </p>
            </div>

            <div className="field">
              <label>Solutions this agent may present</label>
              <div className="row wrap" style={{ gap: 8 }}>
                {(book?.solutions || []).map(s => (
                  <label key={s.id} className="pill gray" style={{ cursor: 'pointer', display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                    <input type="checkbox" style={{ width: 'auto', margin: 0 }}
                      checked={solutionOn(s.id)} onChange={() => toggleSolution(s.id)} />
                    {s.label}
                  </label>
                ))}
                {!book && <span className="sm mut">loading catalogue…</span>}
              </div>
              <p className="sm mut" style={{ margin: '8px 0 0' }}>
                Untick anything this agent should not raise. The agent still reads
                each company and picks <b>one</b> solution that matches a problem it
                can actually see — it never lists services and never sends a menu.
              </p>
            </div>

            {book?.solutions?.length > 0 && (
              <details className="card mb" style={{ padding: 14 }}>
                <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: 13 }}>
                  What the agent can lean on — problems, outcomes and proof
                </summary>
                <div style={{ marginTop: 10, display: 'grid', gap: 10 }}>
                  {book.solutions.map(s => (
                    <div key={s.id}>
                      <b style={{ fontSize: 13, color: 'var(--navy)' }}>{s.label}</b>
                      <p className="sm mut" style={{ margin: '2px 0 0' }}><b>When:</b> {s.when}</p>
                      <p className="sm mut" style={{ margin: '2px 0 0' }}><b>Outcome:</b> {s.outcome}</p>
                      <p className="sm mut" style={{ margin: '2px 0 0' }}><b>Proof:</b> {s.proof}</p>
                    </div>
                  ))}
                </div>
              </details>
            )}

            <div className="field">
              <label>Avoid phrases — never in a subject, never in the body</label>
              <textarea rows={3} value={edit.avoid_phrases}
                onChange={e => set('avoid_phrases', e.target.value)}
                placeholder={'e.g. revolutionary, free consultation, I hope this email finds you well, we are an agency'} />
              <p className="sm mut" style={{ margin: '4px 0 0' }}>
                Removed from every generated email after writing, so a hit costs a
                rewrite instead of a send. Built-in defaults always apply on top:
                {' '}<span style={{ opacity: .8 }}>{(book?.avoid_phrases || []).slice(0, 14).join(', ')}
                {(book?.avoid_phrases || []).length > 14 ? ` … +${book.avoid_phrases.length - 14} more` : ''}</span>
              </p>
            </div>
            <div className="field"><label>Persona prompt — how this agent thinks &amp; writes</label>
              <textarea rows={5} value={edit.persona_prompt} onChange={e => set('persona_prompt', e.target.value)}
                placeholder="Leave empty to use the built-in playbook for Osaja / Saif / Aleem / Dawood" /></div>
            <div className="field"><label>Sentiment layer — reads the other person's mood &amp; matches it</label>
              <textarea rows={3} value={edit.sentiment_prompt} onChange={e => set('sentiment_prompt', e.target.value)}
                placeholder="e.g. If they sound busy or stressed, be short and respectful; if warm and chatty, be a little warmer; never robotic. Mirror their energy naturally while staying professional." /></div>
            <div className="field"><label>Country / region layer — writes the way this market expects</label>
              <textarea rows={3} value={edit.country_prompt} onChange={e => set('country_prompt', e.target.value)}
                placeholder="e.g. Europe: concise, formal but warm. US: confident, casual-professional, benefit-led. Middle East: relationship-first, respect titles. Adapt formality and directness to the lead's country." /></div>
            <div className="field"><label>Judgment layer — knows when to ask, when to back off</label>
              <textarea rows={3} value={edit.judgment_prompt} onChange={e => set('judgment_prompt', e.target.value)}
                placeholder="e.g. If they say 'not now', accept it gracefully and leave the door open; if engaged, ask one focused question; never argue, invent, or overpromise." /></div>
            <div className="field"><label>Pitch style notes — objection handling, angles, psychology</label>
              <textarea rows={3} value={edit.pitch_style} onChange={e => set('pitch_style', e.target.value)} /></div>
            <div className="field">
              <label>Extra instructions — your own rules on top of the default prompt</label>
              <textarea rows={4} value={edit.extra_instructions}
                onChange={e => set('extra_instructions', e.target.value)}
                placeholder={'e.g. Always open with something specific to their industry. Never mention pricing. Keep every email under 90 words. Ask at most one question.'} />
              <p className="sm mut" style={{ margin: '4px 0 0' }}>
                The default prompt supplies the core behaviour (voice, targeting,
                solution choice, tone, follow-ups). These stack on top of it and apply
                to outbound and inbound alike. Safety rules still win: no URLs or
                website address, no banned phrases, no excluded recipients.
              </p>
            </div>
            <div className="grid c2">
              <div className="field"><label>Tone</label>
                <select value={edit.tone} onChange={e => set('tone', e.target.value)}>
                  {['professional', 'friendly', 'casual', 'formal'].map(t => <option key={t}>{t}</option>)}
                </select></div>
              <div className="field"><label>Length</label>
                <select value={edit.message_length} onChange={e => set('message_length', e.target.value)}>
                  {['short', 'medium', 'long'].map(t => <option key={t}>{t}</option>)}
                </select></div>
              <div className="field"><label>Portfolio / project URL</label>
                <input value={edit.project_url} onChange={e => set('project_url', e.target.value)} /></div>
              <div className="field"><label>Calendly / meeting link</label>
                <input value={edit.meeting_url} onChange={e => set('meeting_url', e.target.value)} /></div>
              <div className="field"><label title="This agent's own ceiling. The Settings page cap can only make it lower, never higher.">Daily send limit (max)</label>
                <input type="number" value={edit.daily_send_limit} onChange={e => set('daily_send_limit', +e.target.value)} /></div>
              <div className="field"><label>Reply delay (seconds)</label>
                <input type="number" value={edit.reply_delay_seconds} onChange={e => set('reply_delay_seconds', +e.target.value)} /></div>
              <div className="field"><label>Outbound delay min (sec)</label>
                <input type="number" value={edit.outbound_delay_min} onChange={e => set('outbound_delay_min', +e.target.value)} /></div>
              <div className="field"><label>Outbound delay max (sec)</label>
                <input type="number" value={edit.outbound_delay_max} onChange={e => set('outbound_delay_max', +e.target.value)} /></div>
            </div>
            <h2 style={{ marginTop: 18 }}>Mailbox — this agent sends &amp; receives from its own email</h2>
            <p className="sm mut mb">Gmail: smtp.gmail.com / imap.gmail.com with an App Password (2FA on). Hostinger: smtp.hostinger.com / imap.hostinger.com with the mailbox password. Passwords are write-only — blank means "keep saved".</p>
            <div className="grid c2">
              <div className="field"><label>SMTP host</label>
                <input value={edit.smtp_host} onChange={e => set('smtp_host', e.target.value)} placeholder="smtp.gmail.com" /></div>
              <div className="field"><label>SMTP port</label>
                <input type="number" value={edit.smtp_port} onChange={e => set('smtp_port', +e.target.value)} /></div>
              <div className="field"><label>SMTP user (email)</label>
                <input value={edit.smtp_user} onChange={e => set('smtp_user', e.target.value)} placeholder="osaja.chatversio@gmail.com" /></div>
              <div className="field"><label>SMTP password / App Password</label>
                <input type="password" value={edit.smtp_password} onChange={e => set('smtp_password', e.target.value)} placeholder="blank = keep saved" /></div>
              <div className="field"><label>From address</label>
                <input value={edit.smtp_from} onChange={e => set('smtp_from', e.target.value)} placeholder="same as SMTP user" /></div>
              <div className="field"><label>IMAP host</label>
                <input value={edit.imap_host} onChange={e => set('imap_host', e.target.value)} placeholder="imap.gmail.com" /></div>
              <div className="field"><label>IMAP port</label>
                <input type="number" value={edit.imap_port} onChange={e => set('imap_port', +e.target.value)} /></div>
              <div className="field"><label>IMAP user (email)</label>
                <input value={edit.imap_user} onChange={e => set('imap_user', e.target.value)} placeholder="usually same email" /></div>
              <div className="field"><label>IMAP password / App Password</label>
                <input type="password" value={edit.imap_password} onChange={e => set('imap_password', e.target.value)} placeholder="blank = keep saved" /></div>
            </div>
            <div className="field"><label>Signature block (under "Best regards,")</label>
              <textarea rows={3} value={edit.signature} onChange={e => set('signature', e.target.value)}
                placeholder={"Osaja\nSenior Sales Strategist, Chatversio AI"} /></div>
            {testResult && (
              <div className="card" style={{ background: '#f8faff', marginBottom: 12 }}>
                <p className="sm" style={{ color: testResult.smtp.ok ? 'var(--ok)' : 'var(--hot)' }}>
                  <b>SMTP:</b> {testResult.smtp.ok ? '✓ ' : '✗ '}{testResult.smtp.detail}
                </p>
                <p className="sm mt" style={{ color: testResult.imap.ok ? 'var(--ok)' : 'var(--hot)' }}>
                  <b>IMAP:</b> {testResult.imap.ok ? '✓ ' : '✗ '}{testResult.imap.detail}
                </p>
              </div>
            )}
            <div className="row">
              <button className="btn ghost" disabled={testing || !edit.smtp_user || !edit.smtp_password} onClick={testConnection}>
                {testing ? 'Testing…' : 'Test connection'}
              </button>
              <button className="btn" onClick={save}>Save agent</button>
              <button className="btn ghost" onClick={() => setEdit(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
      <Toast toast={toast} />
    </>
  )
}