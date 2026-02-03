/**
 * API client for GroundwaterGPT backend
 */

const API_BASE = '/api'

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
