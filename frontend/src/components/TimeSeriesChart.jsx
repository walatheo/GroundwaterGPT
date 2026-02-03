import { useState, useMemo } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Brush,
  ReferenceLine
} from 'recharts'

export default function TimeSeriesChart({ data, site }) {
  const [showTrend, setShowTrend] = useState(true)
  const [showRollingAvg, setShowRollingAvg] = useState(true)
  const [timeRange, setTimeRange] = useState('all')

  // Calculate rolling average
  const chartData = useMemo(() => {
    if (!data) return []

    const windowSize = 4 // 4 weeks rolling avg
    return data.map((d, i) => {
      const start = Math.max(0, i - windowSize + 1)
      const window = data.slice(start, i + 1)
      const avg = window.reduce((sum, w) => sum + w.level, 0) / window.length

      return {
        ...d,
        rollingAvg: Math.round(avg * 100) / 100
      }
    })
  }, [data])

  // Calculate trend line
  const trendLine = useMemo(() => {
    if (!data || data.length === 0) return { start: 0, end: 0 }

    const n = data.length
    const levels = data.map(d => d.level)
    const sumX = (n * (n - 1)) / 2
    const sumY = levels.reduce((a, b) => a + b, 0)
    const sumXY = levels.reduce((sum, y, i) => sum + i * y, 0)
    const sumX2 = (n * (n - 1) * (2 * n - 1)) / 6

    const slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX)
    const intercept = (sumY - slope * sumX) / n

    return {
      start: intercept,
      end: slope * (n - 1) + intercept
    }
  }, [data])

  // Filter by time range
  const filteredData = useMemo(() => {
    if (timeRange === 'all') return chartData

    const now = new Date()
    const ranges = {
      '1y': 365,
      '2y': 730,
      '5y': 1825
    }

    const days = ranges[timeRange] || 0
    const cutoff = new Date(now.setDate(now.getDate() - days))

    return chartData.filter(d => new Date(d.date) >= cutoff)
  }, [chartData, timeRange])

  if (!data || !site) {
    return (
      <div className="h-[500px] flex items-center justify-center text-slate-400">
        Select a site to view time series data
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
    <div className="p-6">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-4 mb-6">
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={showTrend}
              onChange={(e) => setShowTrend(e.target.checked)}
              className="rounded border-slate-300"
            />
            Show Trend Line
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={showRollingAvg}
              onChange={(e) => setShowRollingAvg(e.target.checked)}
              className="rounded border-slate-300"
            />
            Show Rolling Average
          </label>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">Time Range:</span>
          {['1y', '2y', '5y', 'all'].map(range => (
            <button
              key={range}
              onClick={() => setTimeRange(range)}
              className={`px-3 py-1 text-sm rounded-lg transition-colors ${
                timeRange === range
                  ? 'bg-blue-500 text-white'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              {range === 'all' ? 'All' : range.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Chart */}
      <div className="h-[450px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={filteredData} margin={{ top: 10, right: 30, left: 10, bottom: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 12 }}
              tickFormatter={(value) => {
                const date = new Date(value)
                return `${date.getMonth() + 1}/${date.getFullYear().toString().slice(2)}`
              }}
            />
            <YAxis
              domain={['auto', 'auto']}
              tick={{ fontSize: 12 }}
              reversed
              label={{ value: 'Water Level (ft)', angle: -90, position: 'insideLeft', style: { textAnchor: 'middle' } }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend />

            {/* Raw data */}
            <Line
              type="monotone"
              dataKey="level"
              stroke="#3b82f6"
              strokeWidth={1.5}
              dot={false}
              name="Water Level"
            />

            {/* Rolling average */}
            {showRollingAvg && (
              <Line
                type="monotone"
                dataKey="rollingAvg"
                stroke="#f59e0b"
                strokeWidth={2}
                dot={false}
                name="4-Week Average"
              />
            )}

            {/* Trend line (approximated with reference lines) */}
            {showTrend && (
              <ReferenceLine
                stroke="#ef4444"
                strokeWidth={2}
                strokeDasharray="5 5"
                segment={[
                  { x: filteredData[0]?.date, y: trendLine.start },
                  { x: filteredData[filteredData.length - 1]?.date, y: trendLine.end }
                ]}
              />
            )}

            <Brush
              dataKey="date"
              height={30}
              stroke="#3b82f6"
              tickFormatter={(value) => {
                const date = new Date(value)
                return `${date.getFullYear()}`
              }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Info */}
      <div className="mt-4 p-4 bg-blue-50 rounded-lg text-sm text-blue-800">
        <strong>Note:</strong> Lower values indicate higher water table (closer to surface).
        The trend line shows long-term direction of water levels.
      </div>
    </div>
  )
}
