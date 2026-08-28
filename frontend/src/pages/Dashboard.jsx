import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import Counter from '../Counter.jsx'
import AnimatedChart from '../AnimatedChart.jsx'
import MiniOrb from '../MiniOrb.jsx'
import { IconMail, IconUsers, IconRocket, IconTrash, IconSend, IconInbox, IconTrendUp, IconRefresh } from '../Icons.jsx'

const WINDOWS = ['1d', '15d', '30d', 'all']

function StatCard({ icon: Icon, tone, value, label, sublabel, format }) {
  return (
    <div className="card stat stat-badge">
      <div className={`badge-circle ${tone}`}><Icon /></div>
      <div className="num"><Counter value={value ?? 0} format={format} /></div>
      <div className="lbl">{label}</div>
      {sublabel && <div className="sm mut" style={{ marginTop: 4 }}>{sublabel}</div>}
    </div>
  )
}

export default function Dashboard() {
  const [win, setWin] = useState('30d')
  const [stats, setStats] = useState(null)
  const [series, setSeries] = useState([])
  const [loading, setLoading] = useState(true)

  const loadAll = () => {
    setLoading(true)
    Promise.all([api.stats(win), api.timeseries(15)])
      .then(([s, se]) => { setStats(s); setSeries(se) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }
  useEffect(() => { loadAll() }, [win])
  useEffect(() => { const t = setInterval(loadAll, 30000); return () => clearInterval(t) }, [win])

  const t = stats?.totals || {}
  const temp = stats?.temperature || {}
  const chartData = series.map(d => ({ ...d, label: d.date }))

  const replyRate = t.sent ? Math.round(((t.received || 0) / t.sent) * 100) : 0

  return (
    <>
      {/* Header row: window selector + temperature strip + refresh */}
      <div className="row between mb">
        <div className="row" style={{ gap: 14 }}>
          <MiniOrb size={40} color="#0054FC" accent="#00BAFF" />
          <div className="seg">
            {WINDOWS.map(w => (
              <button key={w} className={win === w ? 'on' : ''} onClick={() => setWin(w)}>
                {w === 'all' ? 'Overall' : w}
              </button>
            ))}
          </div>
        </div>
        <div className="row" style={{ gap: 10 }}>
          <span className="pill hot">Hot {temp.hot || 0}</span>
          <span className="pill warm">Warm {temp.warm || 0}</span>
          <span className="pill cold">Cold {temp.cold || 0}</span>
          <button className="icon-btn" onClick={loadAll} title="Refresh"><IconRefresh /></button>
        </div>
      </div>

      {/* Stat row */}
      <div className="grid c4 mb stagger">
        <StatCard icon={IconSend} tone="blue" value={t.sent} label="Total Outbound Emails"
                  sublabel={`in the last ${win === 'all' ? 'ever' : win}`} />
        <StatCard icon={IconInbox} tone="green" value={t.received} label="Total Inbound Emails"
                  sublabel={`${replyRate}% reply rate`} />
        <StatCard icon={IconUsers} tone="amber" value={t.leads} label="Active leads"
                  sublabel="in the pipeline" />
        <StatCard icon={IconTrash} tone="red" value={t.garbage} label="In garbage"
                  sublabel="unverified / spam" />
      </div>

      {/* Chart + Agents */}
      <div className="grid c2 mb">
        <div className="card">
          <div className="row between mb">
            <div>
              <h3 style={{ fontSize: 15 }}>Email activity</h3>
              <div className="sm mut">Last 15 days — sent vs received</div>
            </div>
            <IconTrendUp style={{ color: 'var(--blue)' }} />
          </div>
          {loading && series.length === 0
            ? <div className="skeleton" style={{ height: 200 }} />
            : <AnimatedChart data={chartData} seriesA={{ key: 'sent', name: 'Sent', color: '#0054FC' }}
                                             seriesB={{ key: 'received', name: 'Received', color: '#00BAFF' }} />}
        </div>
        <div className="card">
          <h3 style={{ fontSize: 15, marginBottom: 4 }}>Agents — {win === 'all' ? 'overall' : `last ${win}`}</h3>
          <div className="sm mut mb">Per-agent activity, live.</div>
          <div className="dashboard-agents">
            {(stats?.per_agent || []).map(a => (
              <div key={a.agent_id} className="dashboard-agent-row">
                <img src={`/${(a.name || '').toLowerCase()}.png`} alt={a.name}
                     className="agent-avatar-sm"
                     onError={(e) => { e.target.style.display = 'none' }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <b>{a.name}</b>
                  <div className="sm mut ellipsis">{a.role}</div>
                </div>
                <div className="row" style={{ gap: 14 }}>
                  <div className="mini-stat"><b><Counter value={a.sent} /></b><span>sent</span></div>
                  <div className="mini-stat"><b><Counter value={a.received} /></b><span>replies</span></div>
                  <span className={`pill ${a.is_active ? 'ok' : 'gray'}`}>{a.is_active ? 'live' : 'paused'}</span>
                </div>
              </div>
            ))}
            {(stats?.per_agent || []).length === 0 && <div className="empty">No agents yet</div>}
          </div>
        </div>
      </div>
    </>
  )
}