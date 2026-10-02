const TOKEN_KEY = 'cv_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token)
    lastRefreshAt = Date.now()   // a brand-new token needs no refresh for a while
  } else {
    localStorage.removeItem(TOKEN_KEY)
    lastRefreshAt = 0
  }
}

export function logout() {
  localStorage.removeItem(TOKEN_KEY)
  window.dispatchEvent(new Event('cv-logout'))
}

// ── Session lifetime ────────────────────────────────────────────────────────
// The token dies after an hour of inactivity (SESSION_IDLE_MINUTES on the
// server) and never outlives 12h from the moment of login. While the user is
// working we slide the idle clock forward with POST /api/auth/refresh, at
// most once every 10 minutes so a busy page can't turn into a refresh storm.
// If that refresh is ever missed, the next real request comes back 401 and
// the handler below drops the user on the login screen.
const REFRESH_AFTER = 10 * 60 * 1000
let lastRefreshAt = 0

async function refreshSession() {
  const headers = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch('/api/auth/refresh', { method: 'POST', headers })
  if (res.status === 401) {
    logout()          // idle/absolute deadline passed — this session is over
    return
  }
  if (!res.ok) return
  const data = await res.json().catch(() => null)
  // Only adopt the new token if the session this refresh was started for is
  // still the one in storage — otherwise a sign-out (or a newer login) that
  // happened while this request was in flight would be silently undone.
  if (data && data.token && getToken() === token) setToken(data.token)
}

function keepAlive() {
  const now = Date.now()
  if (!getToken() || now - lastRefreshAt < REFRESH_AFTER) return
  lastRefreshAt = now
  // Network hiccup -> allow an immediate retry on the next call; a 401 is
  // handled inside refreshSession and must NOT retry in a loop.
  refreshSession().catch(() => { lastRefreshAt = 0 })
}

async function request(path, options = {}) {
  keepAlive()
  const headers = { ...(options.headers || {}) }
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json'
  }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(path, { ...options, headers })

  if (res.status === 401) {
    // login / verify-otp legitimately return 401 for BAD CREDENTIALS —
    // that is a sign-in error, not an expired session. Show the real
    // server message instead of nuking the form with "Session expired".
    const isAuthAttempt = path.startsWith('/api/auth/login') ||
      path.startsWith('/api/auth/verify-otp')
    if (isAuthAttempt) {
      const body = await res.json().catch(() => null)
      const detail = body?.detail
      throw new Error(typeof detail === 'string' && detail
        ? detail : 'Invalid email or password')
    }
    logout()
    throw new Error('Session expired. Please sign in again.')
  }

  if (res.status === 204) return null

  let data = null
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('application/json')) {
    data = await res.json().catch(() => null)
  } else {
    data = await res.text().catch(() => null)
  }

  if (!res.ok) {
    const detail = data?.detail
    const msg = typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map(d => d.msg || JSON.stringify(d)).join('; ')
        : (data?.message || res.statusText || `HTTP ${res.status}`)
    throw new Error(msg)
  }
  return data
}

function qs(params) {
  if (params == null || params === '') return ''
  // Raw string: 'page=2&per_page=20' (also tolerates a leading '?').
  if (typeof params === 'string') {
    const s = params.replace(/^\?/, '')
    return s ? `?${s}` : ''
  }
  // A bare number is a single value — never silently dropped.
  if (typeof params === 'number') return `?${params}`
  // URLSearchParams passed directly (Object.entries would see nothing).
  if (params instanceof URLSearchParams) {
    const s = params.toString()
    return s ? `?${s}` : ''
  }
  const s = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') s.append(k, v)
  })
  const str = s.toString()
  return str ? `?${str}` : ''
}

export const api = {
  // Auth
  login: (email, password) =>
    request('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  verifyOtp: (email, code) =>
    request('/api/auth/verify-otp', { method: 'POST', body: JSON.stringify({ email, code }) }),
  me: () => request('/api/auth/me'),
  logout: () => request('/api/auth/logout', { method: 'POST' }).finally(logout),

  // Dashboard
  stats: (window = '7d') => request(`/api/dashboard/stats${qs({ window })}`),
  timeseries: (days = 15) => request(`/api/dashboard/timeseries${qs({ days })}`),
  notifications: () => request('/api/dashboard/notifications'),
  markRead: () => request('/api/dashboard/notifications/read', { method: 'POST' }),
  monitoring: (params) => request(`/api/dashboard/monitoring${qs(params)}`),
  // Background liveness: DB / Redis / Celery Beat / Worker / inbox poll /
  // LiteLLM gateway, probed server-side (services/health.py).
  health: () => request('/api/dashboard/health'),

  // Agents
  agents: () => request('/api/agents'),
  // Solutions catalogue, persona voices and the built-in Avoid Phrases list —
  // served from the same constants the backend prompt + send gates use.
  agentPlaybook: () => request('/api/agents/playbook'),
  saveAgent: (data, id) =>
    id
      ? request(`/api/agents/${id}`, { method: 'PUT', body: JSON.stringify(data) })
      : request('/api/agents', { method: 'POST', body: JSON.stringify(data) }),
  deleteAgent: (id) => request(`/api/agents/${id}`, { method: 'DELETE' }),   // ← ADD THIS
  toggleAgent: (id) => request(`/api/agents/${id}/toggle`, { method: 'POST' }),
  testMailboxConnection: (payload) =>
    request('/api/agents/test-connection', { method: 'POST', body: JSON.stringify(payload) }),

  // Campaigns
  campaigns: () => request('/api/campaigns'),
  campaignsPaged: (params) => request(`/api/campaigns/paged${qs(params)}`),
  createCampaign: (data) =>
    request('/api/campaigns', { method: 'POST', body: JSON.stringify(data) }),
  updateCampaign: (id, data) =>
    request(`/api/campaigns/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  // The campaign-to-agent selection box: which parts of the agent this
  // campaign's information is allowed to drive (all on by default).
  campaignParts: () => request('/api/campaigns/parts'),
  // The default Agent prompt, straight from the prompt builder.
  defaultPrompt: () => request('/api/agents/default-prompt'),
  toggleCampaign: (id) => request(`/api/campaigns/${id}/toggle`, { method: 'POST' }),
  deleteCampaign: (id) => request(`/api/campaigns/${id}`, { method: 'DELETE' }),
  launch: (cid, leadIds) =>
    request(`/api/campaigns/${cid}/launch`, {
      method: 'POST',
      body: JSON.stringify({ lead_ids: leadIds }),
    }),
  batches: (cid) => request(`/api/campaigns/${cid}/batches`),
  deleteBatch: (bid) => request(`/api/campaigns/batches/${bid}`, { method: 'DELETE' }),

  // Leads
  leads: (params) => request(`/api/leads${qs(params)}`),
  leadsPaged: (params) => request(`/api/leads/paged${qs(params)}`),
  leadsStats: () => request('/api/leads/stats'),
  // Upload is QUEUED: POST returns 202 + job_id immediately, then the page
  // polls uploadJob(id) for the progress bar. Do not expect leads back here.
  // batchSize is optional — omit it and the server uses the Settings-page
  // "email batch size", which is the only place that decides it.
  uploadLeads: (file, agentId, campaignId, source = 'excel', batchSize = null, autoEnroll = true) => {
    const fd = new FormData()
    fd.append('file', file)
    if (agentId) fd.append('agent_id', agentId)
    if (campaignId) fd.append('campaign_id', campaignId)
    const src = source === 'pitch' ? 'pitch' : 'excel'
    return request(
      `/api/leads/upload${qs({ source: src, batch_size: batchSize, auto_enroll: autoEnroll })}`,
      { method: 'POST', body: fd })
  },
  uploadJob: (id) => request(`/api/leads/upload/${id}`),
  importJobs: (kind) => request(`/api/leads/jobs${qs({ kind })}`),
  cancelImport: (id) => request(`/api/leads/upload/${id}/cancel`, { method: 'POST' }),
  manualPitchLead: (data) =>
    request('/api/leads/manual-pitch', { method: 'POST', body: JSON.stringify(data) }),
  enroll: (leadIds, campaignId, agentId) =>
    request('/api/leads/enroll', {
      method: 'POST',
      body: JSON.stringify({ lead_ids: leadIds, campaign_id: campaignId, agent_id: agentId }),
    }),
  enrollByFilter: (filter, campaignId, agentId) =>
    request('/api/leads/enroll', {
      method: 'POST',
      body: JSON.stringify({ filter, campaign_id: campaignId, agent_id: agentId }),
    }),
  // Enroll whole batches (20/30/40/50 groups) or every lead from one Excel.
  enrollBatches: (batchIds, campaignId, agentId) =>
    request('/api/leads/enroll', {
      method: 'POST',
      body: JSON.stringify({ batch_ids: batchIds, campaign_id: campaignId, agent_id: agentId }),
    }),
  enrollSourceFile: (sourceFile, campaignId, agentId) =>
    request('/api/leads/enroll', {
      method: 'POST',
      body: JSON.stringify({ source_file: sourceFile, campaign_id: campaignId, agent_id: agentId }),
    }),
  research: (leadId) => request(`/api/leads/${leadId}/research`, { method: 'POST' }),
  deleteLead: (id) => request(`/api/leads/${id}`, { method: 'DELETE' }),
  bulkDeleteLeads: (ids) =>
    request('/api/leads/bulk-delete', { method: 'POST', body: JSON.stringify({ ids }) }),
  bulkGarbageLeads: (ids) =>
    request('/api/leads/bulk-delete', { method: 'POST', body: JSON.stringify({ ids, to_garbage: true }) }),
  deleteAllLeads: () => request('/api/leads/all', { method: 'DELETE' }),
  clearPitchQueue: () => request('/api/leads/pitch-queue', { method: 'DELETE' }),
  purgeCompletedLeads: (days) =>
    request(`/api/leads/purge-completed${qs({ days })}`, { method: 'POST' }),
  unverifiedToGarbage: () =>
    request('/api/leads/bulk-delete', { method: 'POST', body: JSON.stringify({ unverified: true, to_garbage: true }) }),
  // Also a queued job now (MX lookups are DNS, they cannot run in a request).
  verifyMailboxes: (ids) =>
    request('/api/leads/verify', { method: 'POST', body: JSON.stringify({ ids: ids || [], all: true }) }),
  toggleLeadAi: (id) => request(`/api/leads/${id}/toggle-ai`, { method: 'POST' }),
  resolveNeedsHuman: (id, data) =>
    request(`/api/leads/${id}/needs-human/resolve`, { method: 'POST', body: JSON.stringify(data || {}) }),
  campaignSubjectPreview: (id, params = {}) => {
    const q = new URLSearchParams(params).toString()
    return request(`/api/campaigns/${id}/subject-preview${q ? `?${q}` : ''}`)
  },
  manualSend: (leadId, subject, body) =>
    request(`/api/leads/${leadId}/send`, { method: 'POST', body: JSON.stringify({ subject, body }) }),

  // Inbox
  inboxPaged: (params) => request(`/api/inbox${qs(params)}`),
  thread: (leadId, page = 1, perPage = 20) =>
    request(`/api/inbox/thread/${leadId}${qs({ page, per_page: perPage })}`),
  feed: (sinceId, agentId) => request(`/api/inbox/feed${qs({ since_id: sinceId, agent_id: agentId })}`),

  // Knowledge
  knowledge: () => request('/api/knowledge'),
  addDoc: (data) => request('/api/knowledge', { method: 'POST', body: JSON.stringify(data) }),
  uploadDoc: (file, title) => {
    const fd = new FormData()
    fd.append('file', file)
    if (title) fd.append('title', title)
    return request('/api/knowledge/upload', { method: 'POST', body: fd })
  },
  deleteDoc: (id) => request(`/api/knowledge/${id}`, { method: 'DELETE' }),
  templates: () => request('/api/templates'),
  addTemplate: (data) => request('/api/templates', { method: 'POST', body: JSON.stringify(data) }),
  deleteTemplate: (id) => request(`/api/templates/${id}`, { method: 'DELETE' }),

  // Garbage
  garbage: (params) => request(`/api/garbage${qs(params)}`),
  deleteGarbage: (id) => request(`/api/garbage/${id}`, { method: 'DELETE' }),
  bulkDeleteGarbage: (ids) =>
    request('/api/garbage/bulk-delete', { method: 'POST', body: JSON.stringify({ ids }) }),
  clearGarbage: () => request('/api/garbage/clear', { method: 'POST' }),

  // Settings
  settings: () => request('/api/settings'),
  getSettings: () => request('/api/settings'),
  settingsUsage: () => request('/api/settings/usage'),
  saveSettings: (data) => request('/api/settings', { method: 'PUT', body: JSON.stringify(data) }),

  // Pitch
  // NOTE: backend expects lead_id + agent_id as *query params*, not body.
  // Pickup and Ask also carry their body payload separately.
  pitches: (params) => request(`/api/pitch${qs(params)}`),
  pitchRecords: (params) => request(`/api/pitch/records${qs(params)}`),
  markPitchDone: (id) => request(`/api/leads/${id}/pitch-done`, { method: 'POST' }),
  unmarkPitchDone: (id) => request(`/api/leads/${id}/pitch-done`, { method: 'DELETE' }),  // or POST undo
  deleteAllPitches: () => request('/api/pitch/delete-all', { method: 'POST' }),
  generatePitch: (leadId, agentId) =>
    request(`/api/pitch/generate${qs({ lead_id: leadId, agent_id: agentId })}`, { method: 'POST' }),
  generatePickupTranscript: (leadId, agentId, notes) =>
    request(`/api/pitch/pickup${qs({ lead_id: leadId, agent_id: agentId })}`, {
      method: 'POST',
      body: JSON.stringify({ notes }),
    }),
  askPitch: (leadId, agentId, question) =>
    request(`/api/pitch/ask${qs({ lead_id: leadId, agent_id: agentId })}`, {
      method: 'POST',
      body: JSON.stringify({ question }),
    }),
  deletePitch: (id) => request(`/api/pitch/${id}`, { method: 'DELETE' }),
  bulkDeletePitches: (ids) =>
    request('/api/pitch/bulk-delete', { method: 'POST', body: JSON.stringify({ ids }) }),

  // Mail Records
  mailRecords: (params) => request(`/api/mail-records${qs(params)}`),
  mailRecordsAgentSummary: () => request('/api/mail-records/summary/agents'),
  // Batches of 20/30/40/50 grouped by the Excel they came from.
  mailRecordBatches: (params) => request(`/api/mail-records/batches${qs(params)}`),
  mailRecordsFeed: (params) => request(`/api/mail-records/feed/new${qs(params)}`),
  mailRecordsExport: async (params, filename = 'mail-records-report.xlsx') => {
    // Download the Excel report (batch-wise send sheet) with the auth token.
    const headers = {}
    const token = getToken()
    if (token) headers['Authorization'] = `Bearer ${token}`
    const res = await fetch(`/api/mail-records/export${qs(params)}`, { headers })
    if (!res.ok) throw new Error(`Export failed (HTTP ${res.status})`)
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = filename
    document.body.appendChild(a); a.click(); a.remove()
    URL.revokeObjectURL(url)
  },
  deleteMailRecord: (id) => request(`/api/mail-records/${id}`, { method: 'DELETE' }),
  purgeMailOlderThan: (days) =>
    request('/api/mail-records/purge-older-than', {
      method: 'POST',
      body: JSON.stringify({ days }),
    }),

  // Escalation — the "a human must decide" queue. Meeting / scheduling links,
  // promotions, role-account replies (info@/support@/noreply@), system
  // notifications, delivery failures and any outbound we refused to send.
  // Never auto-replied to, never in Mail Records, never in Garbage.
  escalations: (params) => request(`/api/escalations${qs(params)}`),
  escalationsSummary: () => request('/api/escalations/summary'),
  escalationFeed: (sinceId) => request(`/api/escalations/feed/new${qs({ since_id: sinceId })}`),
  escalation: (id) => request(`/api/escalations/${id}`),
  resumeEscalation: (id) => request(`/api/escalations/${id}/resume`, { method: 'POST' }),
  deleteEscalation: (id) => request(`/api/escalations/${id}`, { method: 'DELETE' }),
  bulkDeleteEscalations: (ids) =>
    request('/api/escalations/bulk-delete', { method: 'POST', body: JSON.stringify({ ids }) }),
  clearEscalations: () => request('/api/escalations/clear', { method: 'POST' }),
  purgeEscalations: (days) =>
    request(`/api/escalations/purge-older-than${qs({ days })}`, { method: 'POST' }),

  // Super Admin
  saUsage: (params) => request(`/api/superadmin/usage${qs(params)}`),
  saUsageSeries: (params) => request(`/api/superadmin/usage/timeseries${qs(params)}`),
  saKeys: () => request('/api/superadmin/keys'),
  saSetKey: (name, value) =>
    request(`/api/superadmin/keys/${name}`, { method: 'PUT', body: JSON.stringify({ value }) }),
  saDeleteKey: (name) => request(`/api/superadmin/keys/${name}`, { method: 'DELETE' }),
  saTestKey: (name) => request(`/api/superadmin/keys/${name}/test`, { method: 'POST' }),
  saAuditLog: (params) => request(`/api/superadmin/audit-log${qs(params)}`),
  saSecretsHealth: () => request('/api/superadmin/secrets-health'),
  saBackups: () => request('/api/superadmin/backups'),
  saRunBackup: () => request('/api/superadmin/backups/run-now', { method: 'POST' }),
}