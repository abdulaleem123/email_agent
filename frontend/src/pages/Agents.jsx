import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Toast, useToast } from '../App.jsx'

const BLANK = { name: '', role: '', description: '', persona_prompt: '', pitch_style: '',
  tone: 'professional', message_length: 'medium', project_url: '', meeting_url: '',
  signature: '', daily_send_limit: 150, outbound_delay_min: 180, outbound_delay_max: 720,
  reply_delay_seconds: 900, avatar_url: '',
  smtp_host: '', smtp_port: 587, smtp_user: '', smtp_password: '', smtp_from: '',
  imap_host: '', imap_port: 993, imap_user: '', imap_password: '' }

export default function Agents() {
  const [agents, setAgents] = useState([])
  const [edit, setEdit] = useState(null)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [toast, show] = useToast()

  const load = () => api.agents().then(setAgents).catch(e => show(e.message, true))
  useEffect(() => { load() }, [])

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
              <span className="pill blue">{a.tone}</span>
              <span className="pill gray">{a.message_length}</span>
              <span className="pill gray">{a.daily_send_limit}/day</span>
              <span className="pill gray">out {Math.round(a.outbound_delay_min / 60)}–{Math.round(a.outbound_delay_max / 60)}m</span>
              <span className="pill gray">reply ~{Math.round(a.reply_delay_seconds / 60)}m</span>
              <span className={`pill ${a.smtp_configured ? 'ok' : 'gray'}`}>
                {a.smtp_configured ? `✉ ${a.smtp_user}` : 'no mailbox'}
              </span>
            </div>
            <div className="row mt">
            <button className="btn ghost small" onClick={() => setEdit({ ...a })}>Configure</button>
            <button className="btn ghost small" style={{ color: 'var(--hot)' }} onClick={() => del(a)}>Delete</button>
          </div>
          </div>
        ))}
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
            <div className="field"><label>Persona prompt — how this agent thinks &amp; writes</label>
              <textarea rows={5} value={edit.persona_prompt} onChange={e => set('persona_prompt', e.target.value)}
                placeholder="Leave empty to use the built-in playbook for Osaja / Saif / Aleem / Dawood" /></div>
            <div className="field"><label>Pitch style notes — objection handling, angles, psychology</label>
              <textarea rows={3} value={edit.pitch_style} onChange={e => set('pitch_style', e.target.value)} /></div>
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
              <div className="field"><label>Daily send limit</label>
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