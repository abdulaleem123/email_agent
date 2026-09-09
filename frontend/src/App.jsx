import React, { useEffect, useState, useCallback, useRef, createContext, useContext } from 'react'
import { api, getToken, logout } from './api.js'
import ErrorBoundary from './ErrorBoundary.jsx'
import {
  IconGrid, IconMail, IconBot, IconRocket, IconMic, IconUsers, IconBook,
  IconTrash, IconGear, IconChevronsLeft, IconChevronsRight,
  IconBell, IconSearch, IconLogout, IconShield, IconArchive, IconChevronDown,
} from './Icons.jsx'
import Login from './pages/Login.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Agents from './pages/Agents.jsx'
import Campaigns from './pages/Campaigns.jsx'
import Inbox from './pages/Inbox.jsx'
import Leads from './pages/Leads.jsx'
import Knowledge from './pages/Knowledge.jsx'
import Garbage from './pages/Garbage.jsx'
import Settings from './pages/Settings.jsx'
import SuperAdmin from './pages/SuperAdmin.jsx'
import Pitch from './pages/Pitch.jsx'
import MailRecords from './pages/MailRecords.jsx'

const NAV = [
  ['dashboard', IconGrid, 'Dashboard'],
  ['inbox', IconMail, 'Messages'],
  ['records', IconArchive, 'Mail Records'],
  ['agents', IconBot, 'Agents'],
  ['campaigns', IconRocket, 'Campaigns'],
  ['pitch', IconMic, 'Pitch Decker'],
  ['leads', IconUsers, 'Leads'],
  ['knowledge', IconBook, 'Knowledge'],
  ['garbage', IconTrash, 'Garbage'],
  ['settings', IconGear, 'Settings'],
]

export const LOGO_MARK = '/logo-mark.png'
export const LOGO_FULL = '/logo-full.png'

export function Brand({ light, compact }) {
  return (
    <div className="brand">
      <img src={LOGO_MARK} alt="Chatversio AI" className="brand-mark-img" />
      {!compact && (
        <div className="brand-name" style={light ? { color: '#fff' } : {}}>CHATVERSIO <span>AI</span></div>
      )}
    </div>
  )
}

export function Toast({ toast }) {
  if (!toast) return null
  return <div className={`toast ${toast.err ? 'err' : ''}`}>{toast.msg}</div>
}

export function useToast() {
  const [toast, setToast] = useState(null)
  const show = useCallback((msg, err = false) => {
    setToast({ msg, err })
    setTimeout(() => setToast(null), 3200)
  }, [])
  return [toast, show]
}

// ─── OpenAI Key Context ────────────────────────────────────────────────────────
// Provides { openaiReady: bool | null } to the whole app.
// null  = still loading (unknown)
// false = key missing → AI ops must be disabled
// true  = key present  → AI ops enabled
export const OpenAIKeyContext = createContext({ openaiReady: null })
export function useOpenAIKey() { return useContext(OpenAIKeyContext) }

function NotifBell({ onNavigate }) {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState([])
  const [live, setLive] = useState({ inbound: 0, outbound: 0 })
  const popRef = useRef(null)
  const unread = items.filter(n => !n.read).length

  const load = useCallback(() => {
    api.notifications().then(setItems).catch(() => {})
    api.stats('1d').then(s => {
      const t = s?.totals || {}
      setLive({ inbound: t.received || 0, outbound: t.sent || 0 })
    }).catch(() => {})
  }, [])

  useEffect(() => { load(); const t = setInterval(load, 20000); return () => clearInterval(t) }, [load])

  useEffect(() => {
    const close = (e) => { if (popRef.current && !popRef.current.contains(e.target)) setOpen(false) }
    if (open) document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const openPop = async () => {
    setOpen(o => !o)
    if (!open && unread) { await api.markRead().catch(() => {}); load() }
  }

  return (
    <div ref={popRef} style={{ position: 'relative' }}>
      <button className="nav-bell" onClick={openPop} title="Notifications">
        <IconBell />
        {unread > 0 && <span className="nav-bell-count">{unread > 99 ? '99+' : unread}</span>}
      </button>
      {open && (
        <div className="notif-pop">
          <div className="notif-head">
            <b>Activity</b>
            <span className="sm mut">Last 24h</span>
          </div>
          <div className="notif-stats">
            <div><b>{live.outbound}</b><span>Sent</span></div>
            <div><b>{live.inbound}</b><span>Received</span></div>
            <div><b>{unread}</b><span>New</span></div>
          </div>
          <div className="notif-list">
            {items.length === 0 && <div className="empty sm">You're all caught up.</div>}
            {items.slice(0, 20).map(n => (
              <div key={n.id} className={`n-item ${n.read ? '' : 'unread'}`}
                   onClick={() => { onNavigate?.('inbox'); setOpen(false) }}
                   style={{ cursor: 'pointer' }} title="Open in Messages">
                <div className="row between">
                  <b>{n.title}</b>
                  {n.agent_name && <span className="pill blue" style={{ fontSize: 10 }}>{n.agent_name}</span>}
                </div>
                {n.body && <p>{n.body.slice(0, 160)}</p>}
                <p className="sm mut">{new Date(n.created_at + 'Z').toLocaleString()}</p>
              </div>
            ))}
          </div>
          {items.length > 0 && (
            <button className="n-viewall" onClick={() => { onNavigate?.('inbox'); setOpen(false) }}>
              View all in Messages →
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function NavSearch({ onNavigate }) {
  const [q, setQ] = useState('')
  const [focus, setFocus] = useState(false)

  const opts = [
    ['leads', 'Go to Leads', 'leads'],
    ['campaign', 'Go to Campaigns', 'campaigns'],
    ['messages', 'Open Messages', 'inbox'],
    ['inbox', 'Open Messages', 'inbox'],
    ['mail records', 'Open Mail Records', 'records'],
    ['records', 'Open Mail Records', 'records'],
    ['pitch', 'Open Pitch Decker', 'pitch'],
    ['agents', 'Manage Agents', 'agents'],
    ['knowledge', 'Knowledge base', 'knowledge'],
    ['settings', 'Open Settings', 'settings'],
    ['usage', 'Super Admin — Usage', 'superadmin'],
    ['key', 'Super Admin — API Keys', 'superadmin'],
  ]
  const suggestions = q.trim()
    ? opts.filter(([k]) => k.includes(q.toLowerCase().trim()))
    : []

  const jump = (p) => { onNavigate(p); setQ(''); setFocus(false) }

  return (
    <div className={`nav-search ${focus ? 'focused' : ''}`}>
      <IconSearch />
      <input
        placeholder="Search Chatversio…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => setFocus(true)}
        onBlur={() => setTimeout(() => setFocus(false), 150)}
        onKeyDown={(e) => { if (e.key === 'Enter' && suggestions[0]) jump(suggestions[0][2]) }}
      />
      {focus && q.trim() && (
        <div className="nav-search-pop">
          {suggestions.length === 0 && <div className="empty sm">No matches — try "leads", "campaigns", "messages"…</div>}
          {suggestions.slice(0, 6).map(([k, label, page]) => (
            <button key={k} onMouseDown={() => jump(page)} className="nav-search-item">
              <span>{label}</span>
              <span className="sm mut">↵</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function TodayPill() {
  const [n, setN] = useState(null)
  const load = () => api.stats('1d').then(s => setN((s?.totals?.leads ?? 0))).catch(() => {})
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t) }, [])
  if (n === null) return null
  return <span className="today-pill">Today's new leads <b>{n}</b></span>
}

function UserPill({ me, onNavigate, onSignOut }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    if (open) document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  const initial = (me?.email || '?')[0].toUpperCase()
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button className="user-pill" onClick={() => setOpen(o => !o)}>
        <span className="user-avatar">{initial}</span>
        <span className="user-info">
          <b>{me?.email?.split('@')[0] || 'user'}</b>
          <span className="sm mut">{me?.is_superadmin ? 'Super Admin' : (me?.is_admin ? 'Admin' : 'Member')}</span>
        </span>
        <IconChevronDown />
      </button>
      {open && (
        <div className="user-menu">
          <div className="user-menu-head">
            <b>{me?.email}</b>
            <span className="sm mut">{me?.is_superadmin ? 'Super Admin access' : 'Admin access'}</span>
          </div>
          <button onClick={() => { onNavigate('settings'); setOpen(false) }}>
            <IconGear /> <span>Settings</span>
          </button>
          {me?.is_superadmin && (
            <button onClick={() => { onNavigate('superadmin'); setOpen(false) }}>
              <IconShield /> <span>Super Admin</span>
            </button>
          )}
          <div className="user-menu-sep" />
          <button onClick={onSignOut}>
            <IconLogout /> <span>Sign out</span>
          </button>
        </div>
      )}
    </div>
  )
}

function KeyStatusBanner({ children }) {
  const [openaiReady, setOpenaiReady] = useState(null) // null=loading, false=missing, true=ok

  useEffect(() => {
    let alive = true
    const check = () => api.saKeys()
      .then(ks => {
        if (!alive) return
        const configured = ks.find(k => k.name === 'openai_api_key')?.configured
        setOpenaiReady(configured === true)
      })
      .catch(() => { if (alive) setOpenaiReady(null) })
    check()
    const t = setInterval(check, 30000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  return (
    <OpenAIKeyContext.Provider value={{ openaiReady }}>
      {openaiReady === false && (
        <div className="err mb">
          No OpenAI API key configured — emails cannot be generated.
          Add the key in <b>Super Admin → API Keys</b>. Web research uses DuckDuckGo (free, no key needed).
        </div>
      )}
      {children}
    </OpenAIKeyContext.Provider>
  )
}

export default function App() {
  const [authed, setAuthed] = useState(!!getToken())
  const [me, setMe] = useState(null)
  const [page, setPage] = useState('dashboard')
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('cv_sidebar') === '1')

  useEffect(() => {
    const onLogout = () => { setAuthed(false); setMe(null) }
    window.addEventListener('cv-logout', onLogout)
    return () => window.removeEventListener('cv-logout', onLogout)
  }, [])

  useEffect(() => { if (authed) api.me().then(setMe).catch(() => {}) }, [authed])
  useEffect(() => { localStorage.setItem('cv_sidebar', collapsed ? '1' : '0') }, [collapsed])

  if (!authed) return <Login onAuthed={() => setAuthed(true)} />

  const nav = me?.is_superadmin ? [...NAV, ['superadmin', IconShield, 'Super Admin']] : NAV
  const Page = {
    dashboard: Dashboard, inbox: Inbox, records: MailRecords, agents: Agents,
    campaigns: Campaigns, leads: Leads, knowledge: Knowledge, garbage: Garbage,
    settings: Settings, pitch: Pitch, superadmin: SuperAdmin,
  }[page] || Dashboard
  const title = nav.find(n => n[0] === page)?.[2] || ''

  const signOut = () => { logout(); setAuthed(false) }

  return (
    <div className={`shell ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <aside className="sidebar">
        <div className="row between" style={{ padding: '18px 16px 6px' }}>
          <Brand compact={collapsed} />
        </div>
        <button className="collapse-btn" onClick={() => setCollapsed(c => !c)}
                title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
          {collapsed ? <IconChevronsRight /> : <IconChevronsLeft />}
        </button>
        <nav className="nav">
          {nav.map(([id, Ico, label]) => (
            <button key={id} className={page === id ? 'on' : ''} onClick={() => setPage(id)} title={label}>
              <span className="ico"><Ico /></span><span className="txt">{label}</span>
            </button>
          ))}
        </nav>
        <div className="side-foot">
          <div className="who">{me?.email || ''}</div>
          <button className="signout-btn" onClick={signOut} title="Sign out">
            <IconLogout /> <span className="txt">Sign out</span>
          </button>
        </div>
      </aside>
      <main className="main">
        <div className="topbar">
          <div className="row" style={{ gap: 14, alignItems: 'center' }}>
            <h1>{title}</h1>
          </div>
          <div className="top-actions">
            <NavSearch onNavigate={setPage} />
            <TodayPill />
            <NotifBell onNavigate={setPage} />
            <UserPill me={me} onNavigate={setPage} onSignOut={signOut} />
          </div>
        </div>
        <KeyStatusBanner>
  <ErrorBoundary resetKey={page} onGoHome={() => setPage('dashboard')}>
    <Page />
  </ErrorBoundary>
</KeyStatusBanner>
      </main>
    </div>
  )
}