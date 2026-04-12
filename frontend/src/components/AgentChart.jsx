import { useMemo } from 'react'
import { Download } from 'lucide-react'
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
} from 'recharts'

/**
 * AgentChart — renders Recharts-ready JSON returned by the API's
 * /api/sites/:id/chart and /api/compare/chart endpoints (or the
 * agent's generate_time_series_plot / generate_comparison_chart tools).
 *
 * Props:
 *   chartData – the full JSON payload with { chart_type, title, x_label,
 *               y_label, series, data }
 */
export default function AgentChart({ chartData }) {
  if (!chartData || !chartData.data || chartData.data.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-slate-400 text-sm">
        No chart data available
      </div>
    )
  }

  const {
    title,
    x_label,
    y_label,
    series = [],
    data,
    insights = [],
    cohort_risk_level: cohortRiskLevel,
  } = chartData

  // Determine Y-axis domain from data
  const yDomain = useMemo(() => {
    let min = Infinity
    let max = -Infinity
    for (const row of data) {
      for (const s of series) {
        const v = row[s.key]
        if (v != null) {
          if (v < min) min = v
          if (v > max) max = v
        }
      }
    }
    const pad = (max - min) * 0.05 || 1
    return [Math.floor(min - pad), Math.ceil(max + pad)]
  }, [data, series])

  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-white p-3 rounded-lg shadow-lg border border-slate-200">
          <p className="font-semibold text-slate-800 text-xs mb-1">{label}</p>
          {payload.map((entry, idx) => (
            <p key={idx} style={{ color: entry.color }} className="text-xs">
              {entry.name}: {entry.value} ft
            </p>
          ))}
        </div>
      )
    }
    return null
  }

  const handleDownload = () => {
    const exportSeries = series.filter((s) => !s.isTrend)
    const headers = ['date', ...exportSeries.map(s => s.name || s.key)]
    const escapeCsv = (value) => {
      if (value == null) return ''
      const text = String(value)
      if (text.includes(',') || text.includes('"') || text.includes('\n')) {
        return `"${text.replaceAll('"', '""')}"`
      }
      return text
    }

    const rows = data.map((row) => [
      row.date,
      ...exportSeries.map((s) => row[s.key] ?? ''),
    ])
    const csv = [headers, ...rows]
      .map((row) => row.map(escapeCsv).join(','))
      .join('\n')

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    const baseName = (title || 'groundwater-chart')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '')
    link.href = url
    link.download = `${baseName || 'groundwater-chart'}.csv`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  return (
    <div className="w-full">
      {title && (
        <div className="mb-2 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <h4 className="text-sm font-semibold text-slate-700">
              📊 {title}
            </h4>
            {cohortRiskLevel && (
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                cohortRiskLevel === 'high'
                  ? 'bg-red-100 text-red-700'
                  : cohortRiskLevel === 'moderate'
                    ? 'bg-amber-100 text-amber-700'
                    : 'bg-green-100 text-green-700'
              }`}>
                {cohortRiskLevel} risk
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={handleDownload}
            className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50"
          >
            <Download className="h-3.5 w-3.5" />
            CSV
          </button>
        </div>
      )}

      <div className="h-[320px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 24, left: 8, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10 }}
              tickFormatter={(v) => {
                const d = new Date(v)
                return `${d.getMonth() + 1}/${String(d.getFullYear()).slice(2)}`
              }}
            />
            <YAxis
              domain={yDomain}
              tick={{ fontSize: 10 }}
              reversed
              label={
                y_label
                  ? { value: y_label, angle: -90, position: 'insideLeft', style: { textAnchor: 'middle', fontSize: 11 } }
                  : undefined
              }
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ fontSize: 11 }} />

            {series.map((s) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                stroke={s.color || '#3b82f6'}
                strokeWidth={s.strokeWidth || (s.key === 'rollingAvg' ? 2 : 1.5)}
                strokeDasharray={s.strokeDasharray}
                strokeOpacity={s.opacity ?? 1}
                dot={false}
                name={s.name || s.key}
                connectNulls
              />
            ))}

            {data.length > 60 && (
              <Brush
                dataKey="date"
                height={24}
                stroke="#3b82f6"
                tickFormatter={(v) => String(new Date(v).getFullYear())}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {x_label && (
        <p className="text-center text-xs text-slate-400 mt-1">{x_label}</p>
      )}

      {insights.length > 0 && (
        <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Chart Insights
          </p>
          <ul className="space-y-1 text-xs text-slate-600">
            {insights.map((insight, idx) => (
              <li key={idx}>{insight}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
