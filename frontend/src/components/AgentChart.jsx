import { useMemo, useState } from 'react'
import { Download, FileImage } from 'lucide-react'
import {
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Brush,
  ReferenceDot,
  ReferenceLine,
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
    explainability = null,
    cohort_risk_level: cohortRiskLevel,
    annotations = [],
    climate_series: climateSeries = [],
    climate_correlation: climateCorrelation = null,
    cluster_assignments: clusterAssignments = {},
  } = chartData

  const hasPrecip = climateSeries && climateSeries.length > 0
  const clusterPalette = ['#2563eb', '#dc2626', '#16a34a', '#d97706', '#9333ea']
  const resolvedSeries = useMemo(() => {
    if (!clusterAssignments || Object.keys(clusterAssignments).length < 2) return series
    return series.map((s) => {
      const clusterId = clusterAssignments[s.key]
      if (clusterId == null) return s
      return { ...s, color: clusterPalette[clusterId % clusterPalette.length], clusterId }
    })
  }, [series, clusterAssignments])

  const [showExport, setShowExport] = useState(false)

  const legendPayload = useMemo(() => {
    if (resolvedSeries.length <= 6) return undefined
    return resolvedSeries
      .filter((entry) => entry.highlight || entry.isTrend || entry.key === 'avg')
      .map((entry) => ({
        value: entry.name || entry.key,
        type: 'line',
        id: entry.key,
        color: entry.color || '#3b82f6',
      }))
  }, [resolvedSeries])

  // Determine Y-axis domain from data
  const yDomain = useMemo(() => {
    let min = Infinity
    let max = -Infinity
    for (const row of data) {
      for (const s of resolvedSeries) {
        const v = row[s.key]
        if (v != null) {
          if (v < min) min = v
          if (v > max) max = v
        }
      }
    }
    const pad = (max - min) * 0.05 || 1
    return [Math.floor(min - pad), Math.ceil(max + pad)]
  }, [data, resolvedSeries])

  const precipDomain = useMemo(() => {
    if (!hasPrecip) return undefined
    let max = 0
    for (const row of data) {
      const v = row.precip_mm
      if (v != null && v > max) max = v
    }
    return [0, Math.ceil(max * 1.1) || 1]
  }, [data, hasPrecip])

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

  const handleFigureExport = async (format) => {
    try {
      setShowExport(true)
      const { exportFigure } = await import('../api/client.js')
      const blob = await exportFigure(chartData, format)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      const baseName = (title || 'groundwater-chart')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '')
      link.href = url
      link.download = `${baseName || 'groundwater-chart'}.${format}`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('figure export failed', err)
    } finally {
      setShowExport(false)
    }
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
    link.download = `${baseName || 'groundwater-chart'}-monthly.csv`
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
              {title}
            </h4>
            {cohortRiskLevel && cohortRiskLevel !== 'unknown' && (
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
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleDownload}
              title="Monthly-mean aggregation of all plotted wells"
              className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50"
            >
              <Download className="h-3.5 w-3.5" />
              Monthly CSV
            </button>
            <button
              type="button"
              onClick={() => handleFigureExport('svg')}
              disabled={showExport}
              title="Reproducible SVG rendered server-side from the chart JSON"
              className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-60"
            >
              <FileImage className="h-3.5 w-3.5" />
              {showExport ? '…' : 'SVG'}
            </button>
            <button
              type="button"
              onClick={() => handleFigureExport('png')}
              disabled={showExport}
              title="Reproducible PNG rendered server-side from the chart JSON"
              className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-60"
            >
              <FileImage className="h-3.5 w-3.5" />
              {showExport ? '…' : 'PNG'}
            </button>
          </div>
        </div>
      )}

      <div className="h-[320px]">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 24, left: 8, bottom: 8 }}>
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
              yAxisId="level"
              domain={yDomain}
              tick={{ fontSize: 10 }}
              reversed
              label={
                y_label
                  ? { value: y_label, angle: -90, position: 'insideLeft', style: { textAnchor: 'middle', fontSize: 11 } }
                  : undefined
              }
            />
            {hasPrecip && (
              <YAxis
                yAxisId="precip"
                orientation="right"
                domain={precipDomain}
                tick={{ fontSize: 10 }}
                label={{ value: 'Precip (mm/mo)', angle: 90, position: 'insideRight', style: { textAnchor: 'middle', fontSize: 11 } }}
              />
            )}
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ fontSize: 11 }} payload={legendPayload} />

            {hasPrecip && (
              <Bar
                yAxisId="precip"
                dataKey="precip_mm"
                fill="#60a5fa"
                fillOpacity={0.3}
                name="Precipitation (mm/mo)"
              />
            )}

            {resolvedSeries.map((s) => (
              <Line
                key={s.key}
                yAxisId="level"
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

            {annotations
              .filter((a) => a.type === 'changepoint')
              .map((a, idx) => (
                <ReferenceDot
                  key={`cp-${a.site_id}-${a.date}-${idx}`}
                  yAxisId="level"
                  x={a.date}
                  y={data.find((row) => row.date === a.date)?.[a.site_id]}
                  r={a.highlight ? 5 : 3}
                  fill={a.highlight ? '#dc2626' : '#f97316'}
                  stroke="#fff"
                  strokeWidth={1}
                  label={a.highlight ? { value: 'break', position: 'top', fontSize: 9 } : undefined}
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
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {climateCorrelation && (
        <p className="mt-1 text-[11px] text-slate-500">
          Rainfall correlation (lag {climateCorrelation.lag_months} mo, n={climateCorrelation.n_months}):
          <span className="ml-1 font-medium text-slate-700">r = {climateCorrelation.pearson_r}</span>
          <span className="ml-1">p = {climateCorrelation.pearson_p}</span>
        </p>
      )}

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

      {explainability && (
        <details className="mt-3 rounded-lg border border-cyan-200 bg-cyan-50 p-3">
          <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-wide text-cyan-700">
            How The Model Reads This Chart
          </summary>
          <div className="mt-2 space-y-3 text-xs text-slate-700">
            {explainability.summary && (
              <p>{explainability.summary}</p>
            )}

            {Array.isArray(explainability.how_to_read) && explainability.how_to_read.length > 0 && (
              <div>
                <p className="mb-1 font-semibold text-slate-700">Reading guide</p>
                <ul className="space-y-1">
                  {explainability.how_to_read.map((item, idx) => (
                    <li key={idx}>{item}</li>
                  ))}
                </ul>
              </div>
            )}

            {explainability.llm_role && (
              <p className="border-l-2 border-cyan-300 pl-2 text-slate-600">
                {explainability.llm_role}
              </p>
            )}

            {Array.isArray(explainability.suggested_questions) && explainability.suggested_questions.length > 0 && (
              <div>
                <p className="mb-1 font-semibold text-slate-700">Questions to ask next</p>
                <ul className="space-y-1">
                  {explainability.suggested_questions.map((item, idx) => (
                    <li key={idx}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </details>
      )}
    </div>
  )
}
