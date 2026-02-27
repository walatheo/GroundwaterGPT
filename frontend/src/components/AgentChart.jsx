import { useMemo } from 'react'
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

  const { title, x_label, y_label, series = [], data } = chartData

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

  return (
    <div className="w-full">
      {title && (
        <h4 className="text-sm font-semibold text-slate-700 mb-2 text-center">
          📊 {title}
        </h4>
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
                strokeWidth={s.key === 'rollingAvg' ? 2 : 1.5}
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
    </div>
  )
}
