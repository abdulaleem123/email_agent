let _token = sessionStorage.getItem('cv_token') || ''

export const getToken = () => _token
export const setToken = (t) => { _token = t || ''; t ? sessionStorage.setItem('cv_token', t) : sessionStorage.removeItem('cv_token') }
export const logout = () => {
  setToken('')
  fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }).catch(() => {})
}

// CSRF double-submit: the backend sets a readable (non-httpOnly) cv_csrf
// cookie on login. We read it here and echo it back as a header on every
// state-changing request — a cross-site attacker can ride the session
// cookie automatically but can't read this one to forge the header.
function csrfToken() {
  const m = document.cookie.match(/(?:^|; )cv_csrf=([^;]+)/)
  return m ? decodeURIComponent(m[1]) : ''
}

async function req(path, opts = {}) {
  const headers = { ...(opts.headers || {}) }
  if (_token) headers['Authorization'] = `Bearer ${_token}`
  const method = (opts.method || 'GET').toUpperCase()
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const t = csrfToken()
    if (t) headers['X-CSRF-Token'] = t
  }
  if (opts.body && !(opts.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(opts.body)
  }
  const r = await fetch(path, { ...opts, headers, credentials: 'include' })
  if (r.status === 401 && !path.startsWith('/api/auth')) { setToken(''); window.dispatchEvent(new Event('cv-logout')) }
  if (r.status === 204) return null
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || `Request failed (${r.status})`)
  return data
}

export const api = {
  // auth
  login: (email, password) => req('/api/auth/login', { method: 'POST', body: { email, password } }),
  verifyOtp: (email, code) => req('/api/auth/verify-otp', { method: 'POST', body: { email, code } }),
  me: () => req('/api/auth/me'),
  // super admin (usage + api keys)
  saUsage: (w) => req(`/api/superadmin/usage?window=${w}`),
  saUsageSeries: (d) => req(`/api/superadmin/usage/timeseries?days=${d}`),
  saKeys: () => req('/api/superadmin/keys'),
  saTavilyCredits: () => req('/api/superadmin/tavily-credits'),
  saSetTavilyQuota: (quota) => req('/api/superadmin/tavily-quota', { method: 'PUT', body: { quota } }),
  saAuditLog: (page = 1, perPage = 20) => req(`/api/superadmin/audit-log?page=${page}&per_page=${perPage}`),
  saBackups: () => req('/api/superadmin/backups'),
  saRunBackup: () => req('/api/superadmin/backups/run-now', { method: 'POST' }),
  saSecretsHealth: () => req('/api/superadmin/secrets-health'),
  saSmtpDiagnostic: () => req('/api/superadmin/smtp-diagnostic'),
  saSetKey: (name, value) => req(`/api/superadmin/keys/${name}`, { method: 'PUT', body: { value } }),
  saDeleteKey: (name) => req(`/api/superadmin/keys/${name}`, { method: 'DELETE' }),
  saTestKey: (name) => req(`/api/superadmin/keys/${name}/test`, { method: 'POST' }),
  status: () => req('/api/status'),
  appStatus: () => req('/api/status'),
  // dashboard
  stats: (w) => req(`/api/dashboard/stats?window=${w}`),
  timeseries: (d) => req(`/api/dashboard/timeseries?days=${d}`),
  notifications: () => req('/api/dashboard/notifications'),
  markRead: () => req('/api/dashboard/notifications/read', { method: 'POST' }),
  // agents
  agents: () => req('/api/agents'),
  saveAgent: (a) => a.id ? req(`/api/agents/${a.id}`, { method: 'PUT', body: a }) : req('/api/agents', { method: 'POST', body: a }),
  testMailboxConnection: (a) => req('/api/agents/test-connection', { method: 'POST', body: {
    smtp_host: a.smtp_host, smtp_port: a.smtp_port, smtp_user: a.smtp_user, smtp_password: a.smtp_password,
    imap_host: a.imap_host, imap_port: a.imap_port, imap_user: a.imap_user, imap_password: a.imap_password,
  } }),
  toggleAgent: (id) => req(`/api/agents/${id}/toggle`, { method: 'POST' }),
  toggleLeadAi: (leadId) => req(`/api/leads/${leadId}/toggle-ai`, { method: 'POST' }),
  deleteAgent: (id) => req(`/api/agents/${id}`, { method: 'DELETE' }),
  // leads
  leads: (params = '') => req(`/api/leads${params}`),
  uploadLeads: (file, agentId, campaignId) => { const f = new FormData(); f.append('file', file); if (agentId) f.append('agent_id', agentId); if (campaignId) f.append('campaign_id', campaignId); return req('/api/leads/upload', { method: 'POST', body: f }) },
  enroll: (lead_ids, campaign_id, agent_id) => req('/api/leads/enroll', { method: 'POST', body: { lead_ids, campaign_id, ...(agent_id ? { agent_id } : {}) } }),
  enrollByFilter: (body) => req('/api/leads/enroll-by-filter', { method: 'POST', body }),
  research: (id) => req(`/api/leads/${id}/research`, { method: 'POST' }),
  thread: (id) => req(`/api/leads/${id}/messages`),
  manualSend: (id, subject, body) => req(`/api/leads/${id}/send`, { method: 'POST', body: { subject, body } }),
  deleteLead: (id) => req(`/api/leads/${id}`, { method: 'DELETE' }),
  deleteAllLeads: () => req('/api/leads/all', { method: 'DELETE' }),
  verifyMailboxes: () => req('/api/leads/verify', { method: 'POST' }),
  // pitch decker
  pitches: (leadId) => req(`/api/pitch${leadId != null ? `?lead_id=${leadId}` : ''}`),
  generatePitch: (leadId, agentId) => req(`/api/pitch/generate?lead_id=${leadId}${agentId ? `&agent_id=${agentId}` : ''}`, { method: 'POST' }),
  deletePitch: (id) => req(`/api/pitch/${id}`, { method: 'DELETE' }),
  askPitch: (leadId, agentId, question) => req(`/api/pitch/ask?lead_id=${leadId}${agentId ? `&agent_id=${agentId}` : ''}`, { method: 'POST', body: { question } }),
  pitchRecords: (params = '') => req(`/api/pitch/records${params ? '?' + params : ''}`),
  bulkDeletePitches: (ids) => req('/api/pitch/bulk-delete', { method: 'POST', body: { ids } }),
  // campaigns
  campaigns: () => req('/api/campaigns'),
  campaignsPaged: (page = 1, perPage = 20) => req(`/api/campaigns/paged?page=${page}&per_page=${perPage}`),
  createCampaign: (c) => req('/api/campaigns', { method: 'POST', body: c }),
  updateCampaign: (id, c) => req(`/api/campaigns/${id}`, { method: 'PUT', body: c }),
  toggleCampaign: (id) => req(`/api/campaigns/${id}/toggle`, { method: 'POST' }),
  launch: (id, leadIds) => req(`/api/campaigns/${id}/launch`, { method: 'POST', body: leadIds }),
  batches: (id) => req(`/api/campaigns/${id}/batches`),
  deleteBatch: (bid) => req(`/api/campaigns/batches/${bid}`, { method: 'DELETE' }),
  deleteCampaign: (id) => req(`/api/campaigns/${id}`, { method: 'DELETE' }),
  // inbox
  inbox: (agentId) => req(`/api/inbox${agentId ? `?agent_id=${agentId}` : ''}`),
  // mail records (audit)
  mailRecords: (params = '') => req(`/api/mail-records${params ? '?' + params : ''}`),
  mailRecord: (id) => req(`/api/mail-records/${id}`),
  mailRecordsAgentSummary: () => req('/api/mail-records/summary/agents'),
  deleteMailRecord: (id) => req(`/api/mail-records/${id}`, { method: 'DELETE' }),
  purgeMailOlderThan: (days) => req(`/api/mail-records/purge-older-than?days=${days}`, { method: 'POST' }),
  // leads paged
  leadsPaged: (params = '') => req(`/api/leads/paged${params ? '?' + params : ''}`),
  leadsStats: () => req('/api/leads/stats'),
  bulkDeleteLeads: (ids) => req('/api/leads/bulk-delete', { method: 'POST', body: ids }),
  purgeCompletedLeads: (days) => req(`/api/leads/purge-completed?days=${days}`, { method: 'POST' }),
  bulkGarbageLeads: (ids) => req('/api/leads/bulk-garbage', { method: 'POST', body: ids }),
  unverifiedToGarbage: () => req('/api/leads/unverified-to-garbage', { method: 'POST' }),
  // inbox paged + thread
  inboxPaged: (params = '') => req(`/api/inbox${params ? '?' + params : ''}`),
  thread: (leadId, page = 1, per_page = 20) => req(`/api/inbox/thread/${leadId}?page=${page}&per_page=${per_page}`),

  feed: (sinceId, agentId) => req(`/api/inbox/feed?since_id=${sinceId}${agentId ? `&agent_id=${agentId}` : ''}`),
  // knowledge & templates
  knowledge: (agentId) => req(`/api/knowledge${agentId != null ? `?agent_id=${agentId}` : ''}`),
  addDoc: (d) => req('/api/knowledge', { method: 'POST', body: d }),
  uploadDoc: (file, agentId, title) => { const f = new FormData(); f.append('file', file); if (agentId != null) f.append('agent_id', agentId); if (title) f.append('title', title); return req('/api/knowledge/upload', { method: 'POST', body: f }) },
  deleteDoc: (id) => req(`/api/knowledge/${id}`, { method: 'DELETE' }),
  templates: (agentId) => req(`/api/templates${agentId != null ? `?agent_id=${agentId}` : ''}`),
  addTemplate: (t) => req('/api/templates', { method: 'POST', body: t }),
  deleteTemplate: (id) => req(`/api/templates/${id}`, { method: 'DELETE' }),
  // garbage
  garbage: (page, per) => req(`/api/garbage?page=${page}&per_page=${per}`),
  deleteGarbage: (id) => req(`/api/garbage/${id}`, { method: 'DELETE' }),
  bulkDeleteGarbage: (ids) => req('/api/garbage/bulk-delete', { method: 'POST', body: { ids } }),
  clearGarbage: () => req('/api/garbage/clear', { method: 'POST' }),
  // settings
  settings: () => req('/api/settings'),
  saveSettings: (values) => req('/api/settings', { method: 'PUT', body: { values } }),
}