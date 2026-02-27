/**
 * API client for GroundwaterGPT backend
 */

const API_BASE = '/api'

// ---------------------------------------------------------------------------
// Data endpoints
// ---------------------------------------------------------------------------

export async function fetchSites() {
  const response = await fetch(`${API_BASE}/sites`)
  if (!response.ok) throw new Error('Failed to fetch sites')
  const data = await response.json()
  return data.sites
}

export async function fetchSiteData(siteId) {
  const response = await fetch(`${API_BASE}/sites/${siteId}/data`)
  if (!response.ok) throw new Error(`Failed to fetch data for site ${siteId}`)
  return response.json()
}

export async function fetchHeatmapData(siteId) {
  const response = await fetch(`${API_BASE}/sites/${siteId}/heatmap`)
  if (!response.ok) throw new Error(`Failed to fetch heatmap data for site ${siteId}`)
  return response.json()
}

export async function fetchSiteStats(siteId) {
  const response = await fetch(`${API_BASE}/sites/${siteId}`)
  if (!response.ok) throw new Error(`Failed to fetch stats for site ${siteId}`)
  return response.json()
}

export async function compareSites(siteIds) {
  const response = await fetch(`${API_BASE}/compare?site_ids=${siteIds.join(',')}`)
  if (!response.ok) throw new Error('Failed to compare sites')
  return response.json()
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
  if (!response.ok) throw new Error(`Failed to fetch chart for site ${siteId}`)
  return response.json()
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
  if (!response.ok) throw new Error('Failed to fetch comparison chart')
  return response.json()
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
  if (!response.ok) throw new Error('Chat request failed')
  return response.json()
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
  if (!response.ok) throw new Error('Research request failed')
  return response.json()
}

/**
 * Check agent / research system health.
 * @returns {{ status: string, agent_available: boolean, research_available: boolean, features: string[] }}
 */
export async function fetchChatStatus() {
  const response = await fetch(`${API_BASE}/chat/status`)
  if (!response.ok) throw new Error('Failed to fetch chat status')
  return response.json()
}
