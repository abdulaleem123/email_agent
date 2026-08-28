// import React, { useEffect, useState } from 'react'
// import { api } from '../api.js'
// import { Toast, useToast } from '../App.jsx'
// import AnimatedChart from '../AnimatedChart.jsx'
// import MiniOrb from '../MiniOrb.jsx'
// import Counter from '../Counter.jsx'
// import { IconRocket, IconMail, IconSend, IconShield } from '../Icons.jsx'

// const WINDOWS = ['1d', '7d', '15d', '30d', 'all']

// function money(n) { return '$' + (n ?? 0).toFixed(4) }
// function num(n) { return (n ?? 0).toLocaleString() }

// export default function SuperAdmin() {
//   const [win, setWin] = useState('30d')
//   const [usage, setUsage] = useState(null)
//   const [series, setSeries] = useState([])
//   const [keys, setKeys] = useState([])
//   const [credits, setCredits] = useState(null)
//   const [editing, setEditing] = useState({})    // name -> value being typed
//   const [toast, show] = useToast()

//   const loadUsage = () => { api.saUsage(win).then(setUsage).catch(e => show(e.message, true)) }
//   const loadKeys = () => api.saKeys().then(setKeys).catch(() => {})
//   const loadSeries = () => api.saUsageSeries(15).then(setSeries).catch(() => {})
//   const loadCredits = () => api.saTavilyCredits().then(setCredits).catch(() => setCredits(null))
//   useEffect(() => { loadUsage() }, [win])
//   useEffect(() => { loadSeries(); loadKeys(); loadCredits() }, [])
//   useEffect(() => {
//     const t = setInterval(() => { loadUsage(); loadSeries(); loadCredits() }, 10000)
//     return () => clearInterval(t)
//   }, [win])

//   const saveKey = async (name) => {
//     const value = editing[name] ?? ''
//     if (!value.trim()) return
//     await api.saSetKey(name, value.trim()).catch(e => show(e.message, true))
//     setEditing(e => ({ ...e, [name]: '' })); loadKeys(); show('Key saved — takes effect immediately')
//   }
//   const delKey = async (name) => {
//     if (!confirm('Delete this key? Outbound will pause if Tavily is removed.')) return
//     await api.saDeleteKey(name); loadKeys(); show('Key deleted')
//   }
//   const testKey = async (name) => {
//     show('Testing…')
//     const r = await api.saTestKey(name).catch(e => ({ ok: false, detail: e.message }))
//     show(r.detail || (r.ok ? 'Valid' : 'Failed'), !r.ok)
//   }


//   return (
//     <>
//       <div className="row between mb">
//         <div className="row" style={{ gap: 14 }}>
//           <MiniOrb size={40} color="#001B58" accent="#0054FC" />
//           <div className="seg">
//             {WINDOWS.map(w => (
//               <button key={w} className={win === w ? 'on' : ''} onClick={() => setWin(w)}>
//                 {w === 'all' ? 'Overall' : w}
//               </button>
//             ))}
//           </div>
//         </div>
//         <span className="sm mut">Live · refreshes every 15s</span>
//       </div>

//       <div className="grid c4 mb stagger">
//         <div className="card stat stat-badge">
//           <div className="badge-circle purple"><IconShield /></div>
//           <div className="num">${(usage?.total_cost_usd ?? 0).toFixed(4)}</div>
//           <div className="lbl">Total AI cost</div>
//         </div>
//         <div className="card stat stat-badge">
//           <div className="badge-circle blue"><IconMail /></div>
//           <div className="num"><Counter value={usage?.openai?.input_tokens ?? 0} /></div>
//           <div className="lbl">Input tokens (OpenAI)</div>
//         </div>
//         <div className="card stat stat-badge">
//           <div className="badge-circle green"><IconSend /></div>
//           <div className="num"><Counter value={usage?.openai?.output_tokens ?? 0} /></div>
//           <div className="lbl">Output tokens (OpenAI)</div>
//         </div>
//         <div className={`card stat stat-badge ${credits?.exhausted ? 'stat-exhausted' : ''}`}>
//           <div className={`badge-circle ${credits?.exhausted ? 'red' : 'amber'}`}><IconRocket /></div>
//           <div className="num">
//             <Counter value={credits?.used ?? 0} /> <span className="mut" style={{ fontSize: 16 }}>/ {credits?.quota ?? 1000}</span>
//           </div>
//           <div className="lbl">Tavily credits used {credits?.exhausted && <b style={{ color: 'var(--hot)' }}>· EXHAUSTED</b>}</div>
//           <div className="row sm mt" style={{ gap: 6 }}>
//             <input type="number" min={0} placeholder="quota" defaultValue={credits?.quota ?? 1000}
//                    style={{ width: 90, padding: '5px 8px' }}
//                    onKeyDown={async (e) => {
//                      if (e.key !== 'Enter') return
//                      const q = Number(e.target.value)
//                      if (!q || q < 0) return
//                      const r = await api.saSetTavilyQuota(q).catch(err => { show(err.message, true); return null })
//                      if (r) { setCredits(r); show(`Quota set to ${q}`) }
//                    }} />
//             <span className="mut" style={{ fontSize: 11 }}>Enter to save</span>
//           </div>
//         </div>
//       </div>

//       {credits?.exhausted && (
//         <div className="err mb">
//           Tavily credits exhausted ({credits.used}/{credits.quota}) — <b>ALL outbound campaigns
//           have been paused automatically.</b> Inbound replies keep working (they don't use
//           Tavily). Raise the quota above once your plan resets, or add/replace the key below,
//           then resume campaigns manually from the Campaigns page.
//         </div>
//       )}

//       <div className="grid c2 mb">
//         <div className="card">
//           <div className="row between mb">
//             <h3 style={{ fontSize: 15 }}>Token usage <span className="live-dot" style={{ marginLeft: 6 }} /></h3>
//             <span className="sm mut">Live · updates every 10s</span>
//           </div>
//           <AnimatedChart data={series.map(d => ({ ...d, label: d.date }))}
//                         seriesA={{ key: 'input_tokens', name: 'Input', color: '#0054FC' }}
//                         seriesB={{ key: 'output_tokens', name: 'Output', color: '#00BAFF' }} />
//         </div>
//         <div className="card">
//           <h3 style={{ fontSize: 15, marginBottom: 10 }}>Per model</h3>
//           <table>
//             <thead><tr><th>Model</th><th>Calls</th><th>In</th><th>Out</th><th>Cost</th></tr></thead>
//             <tbody>
//               {(usage?.per_model || []).map(m => (
//                 <tr key={m.model}><td>{m.model}</td><td>{num(m.calls)}</td>
//                   <td>{num(m.input_tokens)}</td><td>{num(m.output_tokens)}</td><td>{money(m.cost_usd)}</td></tr>
//               ))}
//               {(usage?.per_model || []).length === 0 && <tr><td colSpan={5}><div className="empty">No calls yet</div></td></tr>}
//             </tbody>
//           </table>
//         </div>
//       </div>

//       <div className="card mb">
//         <h3 style={{ fontSize: 15, marginBottom: 10 }}>Per agent — token &amp; cost consumption</h3>
//         <table>
//           <thead><tr><th>Agent</th><th>Calls</th><th>Input tokens</th><th>Output tokens</th><th>Cost</th></tr></thead>
//           <tbody>
//             {(usage?.per_agent || []).map(a => (
//               <tr key={String(a.agent_id)}>
//                 <td><b>{a.name}</b></td><td>{num(a.calls)}</td>
//                 <td>{num(a.input_tokens)}</td><td>{num(a.output_tokens)}</td><td>{money(a.cost_usd)}</td>
//               </tr>
//             ))}
//             {(usage?.per_agent || []).length === 0 && <tr><td colSpan={5}><div className="empty">No agent usage yet</div></td></tr>}
//           </tbody>
//         </table>
//       </div>

//       <div className="card">
//         <h3 style={{ fontSize: 15, marginBottom: 4 }}>API keys</h3>
//         <p className="sm mut mb">OpenAI and Tavily keys are managed <b>only here</b> — not in .env, not in any other page. Encrypted at rest (AES-GCM) when the optional <code>cryptography</code> package is installed; otherwise stored server-side only (never sent to the browser). Used immediately, no restart. Exhausted Tavily quota auto-pauses ALL outbound campaigns (inbound keeps working).</p>
//         {keys.map(k => (
//           <div key={k.name} className="row between" style={{ padding: '12px 0', borderBottom: '1px solid var(--line)' }}>
//             <div style={{ minWidth: 150 }}>
//               <b>{k.label}</b>
//               <div className="sm mut">{k.configured ? `${k.masked} · ${k.source}` : 'not set'}</div>
//             </div>
//             <div className="row" style={{ flex: 1, justifyContent: 'flex-end' }}>
//               <input style={{ maxWidth: 280 }} type="password" placeholder={`New ${k.label} key`}
//                 value={editing[k.name] || ''} onChange={e => setEditing(s => ({ ...s, [k.name]: e.target.value }))} />
//               <button className="btn small" onClick={() => saveKey(k.name)}>Save</button>
//               <button className="btn ghost small" onClick={() => testKey(k.name)}>Test</button>
//               <button className="btn danger small" disabled={!k.configured} onClick={() => delKey(k.name)}>Delete</button>
//             </div>
//           </div>
//         ))}
//       </div>
//       <Toast toast={toast} />
//     </>
//   )
// }


import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Toast, useToast } from '../App.jsx'
import AnimatedChart from '../AnimatedChart.jsx'
import MiniOrb from '../MiniOrb.jsx'
import Counter from '../Counter.jsx'
import { IconRocket, IconMail, IconSend, IconShield } from '../Icons.jsx'

const WINDOWS = ['1d', '7d', '15d', '30d', 'all']

function money(n) { return '$' + (n ?? 0).toFixed(4) }
function num(n) { return (n ?? 0).toLocaleString() }

export default function SuperAdmin() {
  const [win, setWin] = useState('30d')
  const [usage, setUsage] = useState(null)
  const [series, setSeries] = useState([])
  const [keys, setKeys] = useState([])
  const [credits, setCredits] = useState(null)
  const [editing, setEditing] = useState({})    // name -> value being typed
  const [toast, show] = useToast()

  // security & ops
  const [secretsHealth, setSecretsHealth] = useState(null)
  const [backups, setBackups] = useState({ backups: [], keep: 14 })
  const [backupBusy, setBackupBusy] = useState(false)
  const [showAudit, setShowAudit] = useState(false)
  const [audit, setAudit] = useState({ items: [], total: 0, page: 1, pages: 1 })
  const [auditPage, setAuditPage] = useState(1)

  const loadUsage = () => { api.saUsage(win).then(setUsage).catch(e => show(e.message, true)) }
  const loadKeys = () => api.saKeys().then(setKeys).catch(() => {})
  const loadSeries = () => api.saUsageSeries(15).then(setSeries).catch(() => {})
  const loadCredits = () => api.saTavilyCredits().then(setCredits).catch(() => setCredits(null))
  const loadSecretsHealth = () => api.saSecretsHealth().then(setSecretsHealth).catch(() => {})
  const loadBackups = () => api.saBackups().then(setBackups).catch(() => {})
  const loadAudit = () => api.saAuditLog(auditPage, 20).then(setAudit).catch(e => show(e.message, true))

  useEffect(() => { loadUsage() }, [win])
  useEffect(() => { loadSeries(); loadKeys(); loadCredits(); loadSecretsHealth(); loadBackups() }, [])
  useEffect(() => {
    const t = setInterval(() => { loadUsage(); loadSeries(); loadCredits() }, 10000)
    return () => clearInterval(t)
  }, [win])
  useEffect(() => { if (showAudit) loadAudit() }, [showAudit, auditPage])

  const runBackupNow = async () => {
    setBackupBusy(true)
    try { await api.saRunBackup(); show('Backup created'); loadBackups() }
    catch (e) { show(e.message, true) } finally { setBackupBusy(false) }
  }

  const saveKey = async (name) => {
    const value = editing[name] ?? ''
    if (!value.trim()) return
    await api.saSetKey(name, value.trim()).catch(e => show(e.message, true))
    setEditing(e => ({ ...e, [name]: '' })); loadKeys(); show('Key saved — takes effect immediately')
  }
  const delKey = async (name) => {
    if (!confirm('Delete this key? Outbound will pause if Tavily is removed.')) return
    await api.saDeleteKey(name); loadKeys(); show('Key deleted')
  }
  const testKey = async (name) => {
    show('Testing…')
    const r = await api.saTestKey(name).catch(e => ({ ok: false, detail: e.message }))
    show(r.detail || (r.ok ? 'Valid' : 'Failed'), !r.ok)
  }


  return (
    <>
      <div className="row between mb">
        <div className="row" style={{ gap: 14 }}>
          <MiniOrb size={40} color="#001B58" accent="#0054FC" />
          <div className="seg">
            {WINDOWS.map(w => (
              <button key={w} className={win === w ? 'on' : ''} onClick={() => setWin(w)}>
                {w === 'all' ? 'Overall' : w}
              </button>
            ))}
          </div>
        </div>
        <span className="sm mut">Live · refreshes every 15s</span>
      </div>

      <div className="grid c4 mb stagger">
        <div className="card stat stat-badge">
          <div className="badge-circle purple"><IconShield /></div>
          <div className="num">${(usage?.total_cost_usd ?? 0).toFixed(4)}</div>
          <div className="lbl">Total AI cost</div>
        </div>
        <div className="card stat stat-badge">
          <div className="badge-circle blue"><IconMail /></div>
          <div className="num"><Counter value={usage?.openai?.input_tokens ?? 0} /></div>
          <div className="lbl">Input tokens (OpenAI)</div>
        </div>
        <div className="card stat stat-badge">
          <div className="badge-circle green"><IconSend /></div>
          <div className="num"><Counter value={usage?.openai?.output_tokens ?? 0} /></div>
          <div className="lbl">Output tokens (OpenAI)</div>
        </div>
        <div className={`card stat stat-badge ${credits?.exhausted ? 'stat-exhausted' : ''}`}>
          <div className={`badge-circle ${credits?.exhausted ? 'red' : 'amber'}`}><IconRocket /></div>
          <div className="num">
            <Counter value={credits?.used ?? 0} /> <span className="mut" style={{ fontSize: 16 }}>/ {credits?.quota ?? 1000}</span>
          </div>
          <div className="lbl">Tavily credits used {credits?.exhausted && <b style={{ color: 'var(--hot)' }}>· EXHAUSTED</b>}</div>
          <div className="row sm mt" style={{ gap: 6 }}>
            <input type="number" min={0} placeholder="quota" defaultValue={credits?.quota ?? 1000}
                   style={{ width: 90, padding: '5px 8px' }}
                   onKeyDown={async (e) => {
                     if (e.key !== 'Enter') return
                     const q = Number(e.target.value)
                     if (!q || q < 0) return
                     const r = await api.saSetTavilyQuota(q).catch(err => { show(err.message, true); return null })
                     if (r) { setCredits(r); show(`Quota set to ${q}`) }
                   }} />
            <span className="mut" style={{ fontSize: 11 }}>Enter to save</span>
          </div>
        </div>
      </div>

      {credits?.exhausted && (
        <div className="err mb">
          Tavily credits exhausted ({credits.used}/{credits.quota}) — <b>ALL outbound campaigns
          have been paused automatically.</b> Inbound replies keep working (they don't use
          Tavily). Raise the quota above once your plan resets, or add/replace the key below,
          then resume campaigns manually from the Campaigns page.
        </div>
      )}

      <div className="grid c2 mb">
        <div className="card">
          <div className="row between mb">
            <h3 style={{ fontSize: 15 }}>Token usage <span className="live-dot" style={{ marginLeft: 6 }} /></h3>
            <span className="sm mut">Live · updates every 10s</span>
          </div>
          <AnimatedChart data={series.map(d => ({ ...d, label: d.date }))}
                        seriesA={{ key: 'input_tokens', name: 'Input', color: '#0054FC' }}
                        seriesB={{ key: 'output_tokens', name: 'Output', color: '#00BAFF' }} />
        </div>
        <div className="card">
          <h3 style={{ fontSize: 15, marginBottom: 10 }}>Per model</h3>
          <table>
            <thead><tr><th>Model</th><th>Calls</th><th>In</th><th>Out</th><th>Cost</th></tr></thead>
            <tbody>
              {(usage?.per_model || []).map(m => (
                <tr key={m.model}><td>{m.model}</td><td>{num(m.calls)}</td>
                  <td>{num(m.input_tokens)}</td><td>{num(m.output_tokens)}</td><td>{money(m.cost_usd)}</td></tr>
              ))}
              {(usage?.per_model || []).length === 0 && <tr><td colSpan={5}><div className="empty">No calls yet</div></td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card mb">
        <h3 style={{ fontSize: 15, marginBottom: 10 }}>Per agent — token &amp; cost consumption</h3>
        <table>
          <thead><tr><th>Agent</th><th>Calls</th><th>Input tokens</th><th>Output tokens</th><th>Cost</th></tr></thead>
          <tbody>
            {(usage?.per_agent || []).map(a => (
              <tr key={String(a.agent_id)}>
                <td><b>{a.name}</b></td><td>{num(a.calls)}</td>
                <td>{num(a.input_tokens)}</td><td>{num(a.output_tokens)}</td><td>{money(a.cost_usd)}</td>
              </tr>
            ))}
            {(usage?.per_agent || []).length === 0 && <tr><td colSpan={5}><div className="empty">No agent usage yet</div></td></tr>}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3 style={{ fontSize: 15, marginBottom: 4 }}>API keys</h3>
        <p className="sm mut mb">OpenAI and Tavily keys are managed <b>only here</b> — not in .env, not in any other page. Encrypted at rest (AES-GCM) when the optional <code>cryptography</code> package is installed; otherwise stored server-side only (never sent to the browser). Used immediately, no restart. Exhausted Tavily quota auto-pauses ALL outbound campaigns (inbound keeps working).</p>
        {keys.map(k => (
          <div key={k.name} className="row between" style={{ padding: '12px 0', borderBottom: '1px solid var(--line)' }}>
            <div style={{ minWidth: 150 }}>
              <b>{k.label}</b>
              <div className="sm mut">{k.configured ? `${k.masked} · ${k.source}` : 'not set'}</div>
            </div>
            <div className="row" style={{ flex: 1, justifyContent: 'flex-end' }}>
              <input style={{ maxWidth: 280 }} type="password" placeholder={`New ${k.label} key`}
                value={editing[k.name] || ''} onChange={e => setEditing(s => ({ ...s, [k.name]: e.target.value }))} />
              <button className="btn small" onClick={() => saveKey(k.name)}>Save</button>
              <button className="btn ghost small" onClick={() => testKey(k.name)}>Test</button>
              <button className="btn danger small" disabled={!k.configured} onClick={() => delKey(k.name)}>Delete</button>
            </div>
          </div>
        ))}
      </div>

      {secretsHealth?.warnings?.length > 0 && (
        <div className="err mb">
          <b>Secrets rotation overdue:</b>
          <ul style={{ margin: '6px 0 0 18px' }}>
            {secretsHealth.warnings.map((w, i) => <li key={i}>{w.message}</li>)}
          </ul>
        </div>
      )}

      <div className="grid c2 mb">
        <div className="card">
          <div className="row between mb">
            <h3 style={{ fontSize: 15 }}>Database backups</h3>
            <button className="btn small" disabled={backupBusy} onClick={runBackupNow}>
              {backupBusy ? 'Backing up…' : 'Run backup now'}
            </button>
          </div>
          <p className="sm mut mb">Runs automatically once a day · keeps the newest {backups.keep}.</p>
          {backups.backups?.length === 0 && <div className="empty">No backups yet — click "Run backup now".</div>}
          {backups.backups?.slice(0, 6).map(b => (
            <div key={b.file} className="row between sm" style={{ padding: '6px 0', borderBottom: '1px solid var(--line)' }}>
              <span>{b.file}</span>
              <span className="mut">{(b.size_bytes / 1024).toFixed(0)} KB · {new Date(b.created_at + 'Z').toLocaleString()}</span>
            </div>
          ))}
        </div>
        <div className="card">
          <h3 style={{ fontSize: 15, marginBottom: 4 }}>Secrets health</h3>
          <p className="sm mut mb">JWT secret age: <b>{secretsHealth?.jwt_secret_age_days ?? '—'} days</b></p>
          <p className="sm mut">{secretsHealth?.jwt_secret_note}</p>
          {(!secretsHealth?.warnings || secretsHealth.warnings.length === 0) && (
            <p className="sm" style={{ color: 'var(--ok)', marginTop: 8 }}>✓ All API keys rotated within the last 90 days.</p>
          )}
        </div>
      </div>

      <div className="card mb">
        <button className="row between" style={{ width: '100%' }} onClick={() => setShowAudit(s => !s)}>
          <h3 style={{ fontSize: 15 }}>Audit log — who did what, when</h3>
          <span className="sm mut">{showAudit ? 'Hide ▲' : 'Show ▼'}</span>
        </button>
        {showAudit && (
          <>
            <table className="mt">
              <thead><tr><th>User</th><th>Action</th><th>Target</th><th>Detail</th><th>IP</th><th>When</th></tr></thead>
              <tbody>
                {audit.items.map(a => (
                  <tr key={a.id}>
                    <td>{a.user_email || <span className="mut">system</span>}</td>
                    <td><span className="pill blue">{a.action}</span></td>
                    <td className="sm mut">{a.target_type} {a.target_id}</td>
                    <td className="sm mut" style={{ maxWidth: 260 }}>{a.detail}</td>
                    <td className="sm mut">{a.ip_address}</td>
                    <td className="sm mut">{new Date(a.created_at + 'Z').toLocaleString()}</td>
                  </tr>
                ))}
                {audit.items.length === 0 && <tr><td colSpan={6}><div className="empty">No audit entries yet</div></td></tr>}
              </tbody>
            </table>
            <div className="pager mt">
              <button className="btn ghost small" disabled={auditPage <= 1} onClick={() => setAuditPage(p => p - 1)}>← Prev</button>
              <span className="sm mut">Page {audit.page} of {audit.pages} · {audit.total} entries</span>
              <button className="btn ghost small" disabled={auditPage >= audit.pages} onClick={() => setAuditPage(p => p + 1)}>Next →</button>
            </div>
          </>
        )}
      </div>
      <Toast toast={toast} />
    </>
  )
}