const TOKEN_KEY = 'cv_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export function logout() {
  localStorage.removeItem(TOKEN_KEY)
  window.dispatchEvent(new Event('cv-logout'))
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json'
  }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(path, { ...options, headers })

  if (res.status === 401) {
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
  if (!params) return ''
  if (typeof params === 'string') return params ? `?${params}` : ''
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
  timeseries: (window = '7d') => request(`/api/dashboard/timeseries${qs({ window })}`),
  notifications: () => request('/api/dashboard/notifications'),
  markRead: () => request('/api/dashboard/notifications/read', { method: 'POST' }),
  monitoring: () => request('/api/dashboard/monitoring'),

  // Agents
  agents: () => request('/api/agents'),
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
  uploadLeads: (file, agentId, campaignId, source = 'excel') => {
    const fd = new FormData()
    fd.append('file', file)
    if (agentId) fd.append('agent_id', agentId)
    if (campaignId) fd.append('campaign_id', campaignId)
    const src = source === 'pitch' ? 'pitch' : 'excel'
    return request(`/api/leads/upload?source=${src}`, { method: 'POST', body: fd })
  },
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
  research: (leadId) => request(`/api/leads/${leadId}/research`, { method: 'POST' }),
  deleteLead: (id) => request(`/api/leads/${id}`, { method: 'DELETE' }),
  bulkDeleteLeads: (ids) =>
    request('/api/leads/bulk-delete', { method: 'POST', body: JSON.stringify({ ids }) }),
  bulkGarbageLeads: (ids) =>
    request('/api/leads/bulk-delete', { method: 'POST', body: JSON.stringify({ ids, to_garbage: true }) }),
  deleteAllLeads: () => request('/api/leads/all', { method: 'DELETE' }),
  purgeCompletedLeads: () => request('/api/leads/purge-completed', { method: 'POST' }),
  unverifiedToGarbage: () =>
    request('/api/leads/bulk-delete', { method: 'POST', body: JSON.stringify({ unverified: true, to_garbage: true }) }),
  verifyMailboxes: (ids) =>
    request('/api/leads/verify', { method: 'POST', body: JSON.stringify({ ids }) }),
  toggleLeadAi: (id) => request(`/api/leads/${id}/toggle-ai`, { method: 'POST' }),
  manualSend: (leadId, payload) =>
    request(`/api/leads/${leadId}/send`, { method: 'POST', body: JSON.stringify(payload) }),

  // Inbox
  inboxPaged: (params) => request(`/api/inbox${qs(params)}`),
  thread: (leadId) => request(`/api/inbox/thread/${leadId}`),
  feed: (params) => request(`/api/inbox/feed${qs(params)}`),

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
  mailRecordsFeed: (params) => request(`/api/mail-records/feed/new${qs(params)}`),
  deleteMailRecord: (id) => request(`/api/mail-records/${id}`, { method: 'DELETE' }),
  purgeMailOlderThan: (days) =>
    request('/api/mail-records/purge-older-than', {
      method: 'POST',
      body: JSON.stringify({ days }),
    }),

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