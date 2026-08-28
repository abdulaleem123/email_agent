// import React, { useEffect, useState } from 'react'
// import { api } from '../api.js'
// import { Toast, useToast } from '../App.jsx'

// const TOGGLES = [
//   ['auto_reply_enabled', 'Autonomous replies', 'Agents reply to inbound emails on their own (per-agent play/pause still applies)'],
//   ['moderation_enabled', 'AI moderation guardrail', 'Every generated email is checked before sending'],
//   ['mx_verify_enabled', 'MX / DNS verification', 'Unverified recipient domains are routed to Garbage instead of being sent'],
//   ['garbage_auto_purge', 'Auto-purge garbage', 'Old garbage is deleted daily so the database never balloons'],
// ]

// const NUMBERS = [
//   ['outbound_delay_min', 'Outbound delay minimum (seconds)', '3 minutes = 180'],
//   ['outbound_delay_max', 'Outbound delay maximum (seconds)', '12 minutes = 720'],
//   ['inbound_reply_delay', 'Inbound reply delay (seconds)', '~15 minutes = 900'],
//   ['followup_after_hours', 'Follow up after silence (hours)', ''],
//   ['max_followups', 'Max follow-ups per lead', ''],
//   ['garbage_retention_days', 'Garbage retention (days)', ''],
// ]

// export default function Settings() {
//   const [vals, setVals] = useState({})
//   const [busy, setBusy] = useState(false)
//   const [toast, show] = useToast()

//   useEffect(() => { api.settings().then(setVals).catch(e => show(e.message, true)) }, [])

//   const flip = async (key) => {
//     const next = { ...vals, [key]: vals[key] === 'true' ? 'false' : 'true' }
//     setVals(next)
//     await api.saveSettings({ [key]: next[key] }).catch(e => show(e.message, true))
//     show('Saved — takes effect immediately')
//   }
//   const saveNumbers = async () => {
//     setBusy(true)
//     try {
//       const nums = Object.fromEntries(NUMBERS.map(([k]) => [k, String(vals[k] ?? '')]))
//       setVals(await api.saveSettings(nums))
//       show('Delays & limits saved')
//     } catch (e) { show(e.message, true) } finally { setBusy(false) }
//   }

//   return (
//     <>
//       <div className="grid c2">
//         <div className="card">
//           <h3 style={{ fontSize: 15, marginBottom: 14 }}>System toggles</h3>
//           {TOGGLES.map(([key, label, hint]) => (
//             <div key={key} className="row between" style={{ padding: '11px 0', borderBottom: '1px solid var(--line)' }}>
//               <div><b className="sm">{label}</b><div className="sm mut">{hint}</div></div>
//               <div className={`switch ${vals[key] === 'true' ? 'on' : ''}`} onClick={() => flip(key)} role="button" />
//             </div>
//           ))}
//         </div>
//         <div className="card">
//           <h3 style={{ fontSize: 15, marginBottom: 14 }}>Delays &amp; limits</h3>
//           {NUMBERS.map(([key, label, hint]) => (
//             <div key={key} className="field">
//               <label>{label} {hint && <span className="mut">· {hint}</span>}</label>
//               <input type="number" value={vals[key] ?? ''} onChange={e => setVals(v => ({ ...v, [key]: e.target.value }))} />
//             </div>
//           ))}
//           <button className="btn" disabled={busy} onClick={saveNumbers}>Save changes</button>
//           <p className="sm mut mt">Per-agent delays (in each agent's config) override these defaults for that agent.</p>
//         </div>
//       </div>
//       <Toast toast={toast} />
//     </>
//   )
// }


import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Toast, useToast } from '../App.jsx'

const TOGGLES = [
  ['auto_reply_enabled', 'Autonomous replies', 'Agents reply to inbound emails on their own (per-agent play/pause still applies)'],
  ['moderation_enabled', 'AI moderation guardrail', 'Every generated email is checked before sending'],
  ['mx_verify_enabled', 'MX / DNS verification', 'Unverified recipient domains are routed to Garbage instead of being sent'],
  ['garbage_auto_purge', 'Auto-purge garbage', 'Old garbage is deleted daily so the database never balloons'],
]

const NUMBERS = [
  ['outbound_delay_min', 'Outbound delay minimum (seconds)', '3 minutes = 180'],
  ['outbound_delay_max', 'Outbound delay maximum (seconds)', '12 minutes = 720'],
  ['inbound_reply_delay', 'Inbound reply delay (seconds)', '~15 minutes = 900'],
  ['followup_after_hours', 'Follow up after silence (hours)', ''],
  ['max_followups', 'Max follow-ups per lead', ''],
  ['garbage_retention_days', 'Garbage retention (days)', ''],
]

export default function Settings() {
  const [vals, setVals] = useState({})
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [toast, show] = useToast()

  const load = () => {
    setLoading(true); setLoadErr('')
    api.settings()
      .then(v => setVals(v || {}))
      .catch(e => setLoadErr(e.message || 'Could not load settings'))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  if (loading) return <div className="card empty">Loading settings…</div>
  if (loadErr) {
    return (
      <div className="card" style={{ borderColor: '#fecaca' }}>
        <b style={{ color: '#b91c1c' }}>Couldn't load settings</b>
        <p className="sm mut mt">{loadErr}</p>
        <button className="btn mt" onClick={load}>Retry</button>
      </div>
    )
  }

  const flip = async (key) => {
    const next = { ...vals, [key]: vals[key] === 'true' ? 'false' : 'true' }
    setVals(next)
    await api.saveSettings({ [key]: next[key] }).catch(e => show(e.message, true))
    show('Saved — takes effect immediately')
  }
  const saveNumbers = async () => {
    setBusy(true)
    try {
      const nums = Object.fromEntries(NUMBERS.map(([k]) => [k, String(vals[k] ?? '')]))
      setVals(await api.saveSettings(nums))
      show('Delays & limits saved')
    } catch (e) { show(e.message, true) } finally { setBusy(false) }
  }

  return (
    <>
      <div className="grid c2">
        <div className="card">
          <h3 style={{ fontSize: 15, marginBottom: 14 }}>System toggles</h3>
          {TOGGLES.map(([key, label, hint]) => (
            <div key={key} className="row between" style={{ padding: '11px 0', borderBottom: '1px solid var(--line)' }}>
              <div><b className="sm">{label}</b><div className="sm mut">{hint}</div></div>
              <div className={`switch ${vals[key] === 'true' ? 'on' : ''}`} onClick={() => flip(key)} role="button" />
            </div>
          ))}
        </div>
        <div className="card">
          <h3 style={{ fontSize: 15, marginBottom: 14 }}>Delays &amp; limits</h3>
          {NUMBERS.map(([key, label, hint]) => (
            <div key={key} className="field">
              <label>{label} {hint && <span className="mut">· {hint}</span>}</label>
              <input type="number" value={vals[key] ?? ''} onChange={e => setVals(v => ({ ...v, [key]: e.target.value }))} />
            </div>
          ))}
          <button className="btn" disabled={busy} onClick={saveNumbers}>Save changes</button>
          <p className="sm mut mt">Per-agent delays (in each agent's config) override these defaults for that agent.</p>
        </div>
      </div>
      <Toast toast={toast} />
    </>
  )
}
