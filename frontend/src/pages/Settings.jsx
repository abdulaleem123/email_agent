import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Toast, useToast } from '../App.jsx'

/**
 * Settings — the ONE place that decides how much mail goes out.
 *
 * Everything here is global on purpose. There used to be a batch size on the
 * campaign and on the upload form and on the agent, which meant three answers
 * to "how big is a batch" and no way to be sure. Now the operator sets the
 * volume once and every campaign, upload and launch obeys it.
 */

const TOGGLES = [
  ['auto_reply_enabled', 'Autonomous replies', 'Agents reply to inbound emails on their own (per-agent play/pause still applies)'],
  ['moderation_enabled', 'AI moderation guardrail', 'Every generated email is checked before sending'],
  ['mx_verify_enabled', 'MX / DNS verification', 'Unverified recipient domains are routed to Garbage instead of being sent'],
  ['garbage_auto_purge', 'Auto-purge garbage', 'Old garbage is deleted daily so the database never balloons'],
]

// Outbound volume — the three numbers the operator asked to control from here.
const VOLUME = [
  ['daily_send_limit', 'Daily outbound limit (per agent)', 'Hard ceiling for one day. 0 = no global cap, use each agent\'s own limit. An agent set lower than this stays lower.'],
  ['email_batch_size', 'Email batch size', 'Leads per batch. 20 / 30 / 40 / 50. Every uploaded sheet is cut into batches of this size, and a batch never mixes two Excel files.'],
  ['email_poll_size', 'Email poll size (inbox per cycle)', 'How many unread inbound messages one poll reads per mailbox. A bigger backlog is picked up over the next cycles.'],
]

const DELAYS = [
  ['outbound_delay_min', 'Outbound delay min (seconds)', 'min between sends — 180 = 3 min'],
  ['outbound_delay_max', 'Outbound delay max (seconds)', 'max between sends — 720 = 12 min'],
  ['inbound_reply_delay', 'Inbound reply delay (seconds)', 'wait before auto-reply — 900 = 15 min'],
]

const FOLLOWUP = [
  ['followup_after_hours', 'Follow up after silence (hours)', 'fallback when a campaign has no day-plan of its own'],
  ['max_followups', 'Max follow-ups per lead', 'cap used when a campaign has no follow-up count of its own'],
  ['followup_max_days', 'Close sequence after (days)', 'no reply for this long ends the sequence, whatever the plan said'],
]

// Lead ownership — who keeps a lead, and when it becomes available again.
const OWNERSHIP = [
  ['lead_ownership_days', 'Lead ownership timeline (days)', 'A lead stays with its agent while they communicate. Paused agent, or this many days with no mail either way, and any other agent may take it over'],
]

const RETENTION = [
  ['garbage_retention_days', 'Garbage retention (days)', 'auto-purge after this many days'],
  ['escalation_retention_days', 'Escalation retention (days)', 'meeting links, bounces, role replies are kept this long then deleted'],
  ['not_interested_retention_days', 'Not-interested retention (days)', '"not interested" leads sit in Garbage this long. 0 = keep forever'],
  ['stale_lead_days', 'Stale lead (days)', 'no activity for this long and the lead is retired to Garbage'],
]

const ALL = [...VOLUME, ...DELAYS, ...FOLLOWUP, ...OWNERSHIP, ...RETENTION]

function NumberField({ vals, setVals, entry }) {
  const [key, label, hint] = entry
  const lo = vals.bounds?.[key]?.[0]
  const hi = vals.bounds?.[key]?.[1]
  return (
    <div className="field">
      <label>{label} {hint && <span className="mut">· {hint}</span>}</label>
      <input
        type="number"
        min={lo}
        max={hi}
        value={vals[key] ?? ''}
        onChange={e => setVals(v => ({ ...v, [key]: e.target.value }))}
      />
    </div>
  )
}

function NumberCard({ title, note, entries, vals, setVals }) {
  return (
    <div className="card">
      <h3 style={{ fontSize: 15, marginBottom: 4 }}>{title}</h3>
      {note && <p className="sm mut" style={{ margin: '0 0 12px' }}>{note}</p>}
      <div style={{ marginTop: note ? 0 : 10 }}>
        {entries.map(e => <NumberField key={e[0]} vals={vals} setVals={setVals} entry={e} />)}
      </div>
    </div>
  )
}

export default function Settings() {
  const [vals, setVals] = useState({})
  const [usage, setUsage] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [toast, show] = useToast()

  const load = () => {
    setLoading(true); setLoadErr('')
    Promise.all([api.settings(), api.settingsUsage().catch(() => null)])
      .then(([v, u]) => { setVals(v || {}); setUsage(u) })
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

  const saveNumbers = async (keys) => {
    setBusy(true)
    try {
      const nums = Object.fromEntries(keys.map(k => [k, String(vals[k] ?? '')]))
      setVals(await api.saveSettings(nums))
      const u = await api.settingsUsage().catch(() => null)
      if (u) setUsage(u)
      show('Saved — every campaign and agent uses this from the next email')
    } catch (e) { show(e.message, true) } finally { setBusy(false) }
  }

  return (
    <>
      {/* Today at a glance: what the daily cap is actually doing right now. */}
      {usage && (
        <div className="card" style={{ marginBottom: 14 }}>
          <h3 style={{ fontSize: 15, marginBottom: 4 }}>Today&rsquo;s sending</h3>
          <p className="sm mut" style={{ margin: '0 0 10px' }}>
            An agent stops for the day when it reaches its cap. The remaining
            batches are not lost — they are still queued and go out the next day.
          </p>
          <div className="row wrap" style={{ gap: 10 }}>
            <div className="card" style={{ padding: '10px 14px', minWidth: 130 }}>
              <div className="sm mut">Sent today</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{usage.sent_today}</div>
            </div>
            <div className="card" style={{ padding: '10px 14px', minWidth: 130 }}>
              <div className="sm mut">Daily cap (all agents)</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>
                {usage.limit_total ? usage.limit_total : '∞'}
              </div>
            </div>
            <div className="card" style={{ padding: '10px 14px', minWidth: 130 }}>
              <div className="sm mut">Still allowed</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>
                {usage.remaining_total}
              </div>
            </div>
            <div className="card" style={{ padding: '10px 14px', minWidth: 130 }}>
              <div className="sm mut">Batch size</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{usage.email_batch_size}</div>
            </div>
          </div>
          {!!usage.items?.length && (
            <div style={{ marginTop: 12 }}>
              {usage.items.map(it => (
                <div key={it.agent_id} className="row between" style={{ padding: '7px 0', borderBottom: '1px solid var(--line)' }}>
                  <div className="sm">
                    <b>{it.name}</b>
                    <span className="mut"> · {it.sent_today} sent today</span>
                    {it.capped && <span style={{ color: '#b45309' }}> · capped for today</span>}
                  </div>
                  <div className="sm mut">{it.remaining} left of {it.limit}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="grid c2">
        <NumberCard
          title="Sending volume"
          note="These three apply to every agent, campaign, upload and launch. Campaigns no longer carry their own batch size."
          entries={VOLUME}
          vals={vals}
          setVals={setVals}
        />
        <div className="card">
          <h3 style={{ fontSize: 15, marginBottom: 14 }}>System toggles</h3>
          {TOGGLES.map(([key, label, hint]) => (
            <div key={key} className="row between" style={{ padding: '11px 0', borderBottom: '1px solid var(--line)' }}>
              <div><b className="sm">{label}</b><div className="sm mut">{hint}</div></div>
              <div className={`switch ${vals[key] === 'true' ? 'on' : ''}`} onClick={() => flip(key)} role="button" />
            </div>
          ))}
        </div>
        <NumberCard
          title="Delays"
          note="Per-agent delays in each agent's own config still win for that agent."
          entries={DELAYS}
          vals={vals}
          setVals={setVals}
        />
        <NumberCard
          title="Follow-ups"
          note="A campaign can still set its own day-plan and count; these are the global defaults and the safety cutoff."
          entries={FOLLOWUP}
          vals={vals}
          setVals={setVals}
        />
        <NumberCard
          title="Lead ownership"
          note="Pause an agent and its leads become available at once. An agent silent for this many days loses the lead too — another agent can then take the outbound over. A taken-over lead continues as follow-ups, never a second cold email."
          entries={OWNERSHIP}
          vals={vals}
          setVals={setVals}
        />
        <NumberCard
          title="Retention"
          note="How long parked leads and escalations are kept before they are deleted for good."
          entries={RETENTION}
          vals={vals}
          setVals={setVals}
        />
        <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
          <h3 style={{ fontSize: 15, marginBottom: 10 }}>Save</h3>
          <p className="sm mut" style={{ marginTop: 0 }}>
            Every number above is one place. Save once and the next email, batch,
            poll and purge cycle uses the new value — nothing restarts.
          </p>
          <button className="btn" disabled={busy} onClick={() => saveNumbers(ALL.map(k => k[0]))}>
            {busy ? 'Saving…' : 'Save all settings'}
          </button>
        </div>
      </div>
      <Toast toast={toast} />
    </>
  )
}
