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

/**
 * Submit a deep-research question and receive live progress via SSE.
 *
 * The backend streams newline-delimited JSON events in SSE format:
 *   data: {"type":"progress","message":"...","progress":0.33}\n\n
 *   data: {"type":"result", ...full research payload...}\n\n
 *
 * @param {string} question — the research question
 * @param {{
 *   onProgress?: (message: string, progress: number, snapshot?: object) => void,
 *   maxDepth?: number,
 *   timeout?: number
 * }} options
 * @returns {Promise<object>} — resolves with the final result payload when
 *   the stream closes, or rejects on network / parse errors.
 */
export async function sendResearchQueryStreaming(
  question,
  { onProgress, maxDepth = 3, timeout = 120 } = {}
) {
  const response = await fetch(`${API_BASE}/research/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, max_depth: maxDepth, timeout }),
  })

  if (!response.ok) {
    // Non-2xx before the stream started — surface the error immediately.
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail || payload?.message || 'Research stream request failed'
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }

  // ReadableStream reader lets us process the body incrementally.
  const reader = response.body.getReader()
  const decoder = new TextDecoder()

  // SSE lines may be split across multiple chunks, so we accumulate a buffer
  // and only process complete "data: ...\n\n" frames.
  let buffer = ''
  let finalResult = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    // Append the new bytes to whatever was left from the previous chunk.
    buffer += decoder.decode(value, { stream: true })

    // Split on SSE event boundaries (double newline).
    const parts = buffer.split('\n\n')

    // All parts except the last are complete events; the last may be partial.
    buffer = parts.pop() ?? ''

    for (const part of parts) {
      // Strip the "data: " prefix from each SSE line.
      const line = part.trim()
      if (!line.startsWith('data:')) continue

      let event
      try {
        event = JSON.parse(line.slice('data:'.length).trim())
      } catch {
        // Malformed JSON — skip silently (shouldn't happen in normal flow).
        continue
      }

      if (event.type === 'progress') {
        // Forward progress updates to the caller's callback.
        onProgress?.(event.message, event.progress, event.snapshot || null)
      } else if (event.type === 'result') {
        // Store the final payload; don't resolve yet — wait for stream close.
        finalResult = event
      } else if (event.type === 'error') {
        // The server signalled a hard error inside the stream.
        throw new Error(event.message || 'Research agent error')
      }
    }
  }

  if (!finalResult) {
    throw new Error('Research stream closed without a result')
  }

  return finalResult
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
