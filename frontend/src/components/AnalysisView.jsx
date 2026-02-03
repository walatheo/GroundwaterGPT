import { useMemo } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell
} from 'recharts'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export default function AnalysisView({ data, site, stats }) {
  // Calculate monthly statistics
  const monthlyStats = useMemo(() => {
    if (!data) return []

    const byMonth = {}
    data.forEach(d => {
      if (!byMonth[d.month]) byMonth[d.month] = []
      byMonth[d.month].push(d.level)
    })

    return MONTHS.map((name, i) => {
      const values = byMonth[i + 1] || []
      if (values.length === 0) return { month: name, mean: 0, min: 0, max: 0 }

      const mean = values.reduce((a, b) => a + b, 0) / values.length
      return {
        month: name,
        mean: Math.round(mean * 100) / 100,
        min: Math.round(Math.min(...values) * 100) / 100,
        max: Math.round(Math.max(...values) * 100) / 100,
        isDry: [11, 12, 1, 2, 3, 4, 5].includes(i + 1)
      }
    })
  }, [data])

  // Calculate yearly statistics
  const yearlyStats = useMemo(() => {
    if (!data) return []

    const byYear = {}
    data.forEach(d => {
      if (!byYear[d.year]) byYear[d.year] = []
      byYear[d.year].push(d.level)
    })

    return Object.entries(byYear).map(([year, values]) => ({
      year: parseInt(year),
      mean: Math.round((values.reduce((a, b) => a + b, 0) / values.length) * 100) / 100,
      min: Math.round(Math.min(...values) * 100) / 100,
      max: Math.round(Math.max(...values) * 100) / 100,
      count: values.length
    })).sort((a, b) => a.year - b.year)
  }, [data])

  if (!data || !site) {
    return (
      <div className="h-[500px] flex items-center justify-center text-slate-400">
        Select a site to view analysis
      </div>
    )
  }

  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-white p-3 rounded-lg shadow-lg border border-slate-200">
          <p className="font-semibold text-slate-800">{label}</p>
          {payload.map((entry, index) => (
            <p key={index} style={{ color: entry.color }} className="text-sm">
              {entry.name}: {entry.value} ft
            </p>
          ))}
        </div>
      )
    }
    return null
  }

  return (
    <div className="p-6 space-y-8">
      {/* Statistics Summary */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-slate-50 rounded-lg p-4">
            <p className="text-sm text-slate-500">Minimum</p>
            <p className="text-2xl font-bold text-slate-800">{stats.min} ft</p>
          </div>
          <div className="bg-slate-50 rounded-lg p-4">
            <p className="text-sm text-slate-500">Maximum</p>
            <p className="text-2xl font-bold text-slate-800">{stats.max} ft</p>
          </div>
          <div className="bg-slate-50 rounded-lg p-4">
            <p className="text-sm text-slate-500">Mean</p>
            <p className="text-2xl font-bold text-slate-800">{stats.mean} ft</p>
          </div>
          <div className="bg-slate-50 rounded-lg p-4">
            <p className="text-sm text-slate-500">Annual Change</p>
            <p className="text-2xl font-bold text-slate-800">
              {stats.annualChange > 0 ? '+' : ''}{stats.annualChange} ft/yr
            </p>
          </div>
        </div>
      )}

      {/* Seasonal Pattern Chart */}
      <div>
        <h3 className="text-lg font-semibold text-slate-800 mb-4">🌊 Seasonal Pattern</h3>
        <div className="h-[300px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={monthlyStats} margin={{ top: 10, right: 30, left: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="month" tick={{ fontSize: 12 }} />
              <YAxis
                domain={['auto', 'auto']}
                reversed
                tick={{ fontSize: 12 }}
                label={{ value: 'Water Level (ft)', angle: -90, position: 'insideLeft', style: { textAnchor: 'middle' } }}
              />
              <Tooltip content={<CustomTooltip />} />
              <Bar dataKey="mean" name="Mean Level" radius={[4, 4, 0, 0]}>
                {monthlyStats.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={entry.isDry ? '#f59e0b' : '#3b82f6'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="flex justify-center gap-6 mt-4 text-sm">
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 rounded bg-amber-500" />
            <span>🌵 Dry Season (Nov-May)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 rounded bg-blue-500" />
            <span>🌧️ Wet Season (Jun-Oct)</span>
          </div>
        </div>
      </div>

      {/* Yearly Trend Chart */}
      <div>
        <h3 className="text-lg font-semibold text-slate-800 mb-4">📅 Annual Averages</h3>
        <div className="h-[300px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={yearlyStats} margin={{ top: 10, right: 30, left: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="year" tick={{ fontSize: 12 }} />
              <YAxis
                domain={['auto', 'auto']}
                reversed
                tick={{ fontSize: 12 }}
                label={{ value: 'Water Level (ft)', angle: -90, position: 'insideLeft', style: { textAnchor: 'middle' } }}
              />
              <Tooltip content={<CustomTooltip />} />
              <Bar dataKey="mean" name="Mean Level" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Data Table */}
      <div>
        <h3 className="text-lg font-semibold text-slate-800 mb-4">📋 Yearly Summary</h3>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Year</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Mean (ft)</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Min (ft)</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Max (ft)</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">Records</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-slate-200">
              {yearlyStats.map((row) => (
                <tr key={row.year} className="hover:bg-slate-50">
                  <td className="px-4 py-3 text-sm font-medium text-slate-800">{row.year}</td>
                  <td className="px-4 py-3 text-sm text-slate-600">{row.mean}</td>
                  <td className="px-4 py-3 text-sm text-slate-600">{row.min}</td>
                  <td className="px-4 py-3 text-sm text-slate-600">{row.max}</td>
                  <td className="px-4 py-3 text-sm text-slate-600">{row.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
