// Florida USGS Monitoring Sites Data
export const SITES = {
  "251241080385301": {
    id: "251241080385301",
    name: "Miami-Dade G-3764",
    aquifer: "Biscayne Aquifer",
    county: "Miami-Dade",
    lat: 25.2114,
    lon: -80.6481,
    description: "Urban monitoring well in Miami-Dade County"
  },
  "251457080395802": {
    id: "251457080395802",
    name: "Miami-Dade G-3759",
    aquifer: "Biscayne Aquifer",
    county: "Miami-Dade",
    lat: 25.2492,
    lon: -80.6661,
    description: "Monitoring well near Miami"
  },
  "251922080340701": {
    id: "251922080340701",
    name: "Miami-Dade G-3855",
    aquifer: "Biscayne Aquifer",
    county: "Miami-Dade",
    lat: 25.3228,
    lon: -80.5686,
    description: "Eastern Miami-Dade monitoring well"
  },
  "252007080335701": {
    id: "252007080335701",
    name: "Miami-Dade G-561",
    aquifer: "Biscayne Aquifer",
    county: "Miami-Dade",
    lat: 25.3353,
    lon: -80.5658,
    description: "Historic monitoring site"
  },
  "252036080293501": {
    id: "252036080293501",
    name: "Miami-Dade G-1251",
    aquifer: "Biscayne Aquifer",
    county: "Miami-Dade",
    lat: 25.3433,
    lon: -80.4931,
    description: "Coastal monitoring well"
  },
  "262724081260701": {
    id: "262724081260701",
    name: "Lee County - Fort Myers",
    aquifer: "Floridan Aquifer",
    county: "Lee",
    lat: 26.4567,
    lon: -81.4353,
    description: "Deep aquifer monitoring in Fort Myers"
  }
}

// Sample data generator for demo (will be replaced by API)
export function generateSampleData(siteId) {
  const site = SITES[siteId]
  if (!site) return []

  const data = []
  const startDate = new Date('2016-01-01')
  const endDate = new Date('2024-12-31')

  // Base level depends on aquifer type
  const baseLevel = site.aquifer === 'Floridan Aquifer' ? 32 : 2
  const variance = site.aquifer === 'Floridan Aquifer' ? 8 : 1.5

  let currentDate = new Date(startDate)
  let prevLevel = baseLevel

  while (currentDate <= endDate) {
    // Add some seasonal variation and random walk
    const dayOfYear = Math.floor((currentDate - new Date(currentDate.getFullYear(), 0, 0)) / 86400000)
    const seasonal = Math.sin((dayOfYear / 365) * 2 * Math.PI) * (variance * 0.3)
    const random = (Math.random() - 0.5) * variance * 0.2
    const trend = ((currentDate - startDate) / (endDate - startDate)) * (variance * 0.1)

    const level = baseLevel + seasonal + random + trend + (prevLevel - baseLevel) * 0.7

    data.push({
      date: currentDate.toISOString().split('T')[0],
      level: Math.round(level * 100) / 100,
      month: currentDate.getMonth() + 1,
      year: currentDate.getFullYear()
    })

    prevLevel = level
    currentDate.setDate(currentDate.getDate() + 7) // Weekly data
  }

  return data
}

// Calculate statistics from data
export function calculateStats(data) {
  if (!data || data.length === 0) return null

  const levels = data.map(d => d.level)
  const min = Math.min(...levels)
  const max = Math.max(...levels)
  const mean = levels.reduce((a, b) => a + b, 0) / levels.length
  const latest = levels[levels.length - 1]

  // Calculate trend (simple linear regression)
  const n = levels.length
  const sumX = (n * (n - 1)) / 2
  const sumY = levels.reduce((a, b) => a + b, 0)
  const sumXY = levels.reduce((sum, y, i) => sum + i * y, 0)
  const sumX2 = (n * (n - 1) * (2 * n - 1)) / 6

  const slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX)
  const annualChange = slope * 52 // Weekly data, so 52 weeks

  let trend = 'stable'
  if (annualChange > 0.1) trend = 'rising'
  else if (annualChange < -0.1) trend = 'falling'

  return {
    min: Math.round(min * 100) / 100,
    max: Math.round(max * 100) / 100,
    mean: Math.round(mean * 100) / 100,
    latest: Math.round(latest * 100) / 100,
    records: data.length,
    dateRange: `${data[0].date} to ${data[data.length - 1].date}`,
    annualChange: Math.round(annualChange * 1000) / 1000,
    trend
  }
}

// Generate heatmap data
export function generateHeatmapData(data) {
  const heatmap = {}

  data.forEach(d => {
    const key = `${d.year}-${d.month}`
    if (!heatmap[key]) {
      heatmap[key] = { year: d.year, month: d.month, values: [] }
    }
    heatmap[key].values.push(d.level)
  })

  return Object.values(heatmap).map(item => ({
    year: item.year,
    month: item.month,
    level: item.values.reduce((a, b) => a + b, 0) / item.values.length
  }))
}
