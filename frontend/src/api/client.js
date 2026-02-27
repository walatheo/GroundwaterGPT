/**
 * API client for GroundwaterGPT backend
 */

const API_BASE = '/api'

async function parseApiResponse(response, fallbackMessage) {
  let payload = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (!response.ok) {
    const detail =
      (payload && (payload.detail || payload.message || payload.error)) || fallbackMessage
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }

  return payload
}

// ---------------------------------------------------------------------------
// Data endpoints
// ---------------------------------------------------------------------------

export async function fetchSites() {
  const response = await fetch(`${API_BASE}/sites`)
  const data = await parseApiResponse(response, 'Failed to fetch sites')
  return data.sites
}

export async function fetchSiteData(siteId) {
  const response = await fetch(`${API_BASE}/sites/${siteId}/data`)
  return parseApiResponse(response, `Failed to fetch data for site ${siteId}`)
}

export async function fetchHeatmapData(siteId) {
  const response = await fetch(`${API_BASE}/sites/${siteId}/heatmap`)
  return parseApiResponse(response, `Failed to fetch heatmap data for site ${siteId}`)
}

export async function fetchSiteStats(siteId) {
  const response = await fetch(`${API_BASE}/sites/${siteId}`)
  return parseApiResponse(response, `Failed to fetch stats for site ${siteId}`)
}

export async function compareSites(siteIds) {
  const response = await fetch(`${API_BASE}/compare?site_ids=${siteIds.join(',')}`)
  return parseApiResponse(response, 'Failed to compare sites')
}

// ---------------------------------------------------------------------------
// Chart / Visualization endpoints (Session 8)
// ---------------------------------------------------------------------------

/**
 * Fetch Recharts-ready time-series JSON for a single site.
 * @param {string} siteId
 * @param {{ startDate?: string, endDate?: string, rollingWindow?: number }} params
 */
export async function fetchSiteChart(siteId, { startDate, endDate, rollingWindow } = {}) {
  const qs = new URLSearchParams()
  if (startDate) qs.set('start_date', startDate)
  if (endDate) qs.set('end_date', endDate)
  if (rollingWindow) qs.set('rolling_window', rollingWindow)
  const query = qs.toString() ? `?${qs}` : ''
  const response = await fetch(`${API_BASE}/sites/${siteId}/chart${query}`)
  return parseApiResponse(response, `Failed to fetch chart for site ${siteId}`)
}

/**
 * Fetch Recharts-ready multi-site comparison JSON.
 * @param {string[]} siteIds – up to 5 site IDs
 * @param {{ startDate?: string, endDate?: string }} params
 */
export async function fetchComparisonChart(siteIds, { startDate, endDate } = {}) {
  const qs = new URLSearchParams({ site_ids: siteIds.join(',') })
  if (startDate) qs.set('start_date', startDate)
  if (endDate) qs.set('end_date', endDate)
  const response = await fetch(`${API_BASE}/compare/chart?${qs}`)
  return parseApiResponse(response, 'Failed to fetch comparison chart')
}

// ---------------------------------------------------------------------------
// Chat & Research endpoints (Session 7)
// ---------------------------------------------------------------------------

/**
 * Send a chat message to the conversational agent.
 * @param {string} message — the user's question
 * @returns {{ response: string, context: string, sources: string[], mode: string, status: string }}
 */
export async function sendChatMessage(message) {
  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
  return parseApiResponse(response, 'Chat request failed')
}

/**
 * Submit a deep-research question.
 * @param {string} question — the research question
 * @param {{ maxDepth?: number, timeout?: number }} options
 * @returns {{ report: string, insights: object[], sources: string[], mode: string, ... }}
 */
export async function sendResearchQuery(question, { maxDepth = 3, timeout = 120 } = {}) {
  const response = await fetch(`${API_BASE}/research`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, max_depth: maxDepth, timeout }),
  })
  return parseApiResponse(response, 'Research request failed')
}

/**
 * Check agent / research system health.
 * @returns {{ status: string, agent_available: boolean, research_available: boolean, features: string[] }}
 */
export async function fetchChatStatus() {
  const response = await fetch(`${API_BASE}/chat/status`)
  return parseApiResponse(response, 'Failed to fetch chat status')
}

// ---------------------------------------------------------------------------
// Research workflow endpoints (Sprint 2)
// ---------------------------------------------------------------------------

export async function createExperimentPlan(payload) {
  const response = await fetch(`${API_BASE}/research/plans`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return parseApiResponse(response, 'Failed to create experiment plan')
}

export async function listExperimentPlans({ status, limit } = {}) {
  const qs = new URLSearchParams()
  if (status) qs.set('status', status)
  if (limit) qs.set('limit', String(limit))
  const query = qs.toString() ? `?${qs}` : ''
  const response = await fetch(`${API_BASE}/research/plans${query}`)
  return parseApiResponse(response, 'Failed to list experiment plans')
}

export async function getExperimentPlan(planId) {
  const response = await fetch(`${API_BASE}/research/plans/${planId}`)
  return parseApiResponse(response, 'Failed to load experiment plan')
}

export async function logExperimentRun(planId, payload) {
  const response = await fetch(`${API_BASE}/research/plans/${planId}/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return parseApiResponse(response, 'Failed to log experiment run')
}

export async function draftResearchPaper(planId, payload) {
  const response = await fetch(`${API_BASE}/research/plans/${planId}/draft`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return parseApiResponse(response, 'Failed to draft research paper')
}
