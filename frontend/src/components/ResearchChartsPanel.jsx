import { useEffect, useState } from 'react'
import { VChart } from '@visactor/react-vchart'

export default function ResearchChartsPanel({ chartSpecs = [], recommendedViews = [] }) {
  const [selectedId, setSelectedId] = useState(chartSpecs[0]?.id || '')

  useEffect(() => {
    if (!chartSpecs.some(spec => spec.id === selectedId)) {
      setSelectedId(chartSpecs[0]?.id || '')
    }
  }, [chartSpecs, selectedId])

  if (!chartSpecs.length) return null

  const selected = chartSpecs.find(spec => spec.id === selectedId) || chartSpecs[0]
  const visibleRecommended = recommendedViews.filter(view =>
    chartSpecs.some(spec => spec.id === view)
  )

  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Research Views
          </div>
          <div className="text-sm text-slate-700">
            Switch between trend, anomaly, seasonal, and cohort views generated for this query.
          </div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {chartSpecs.map((spec) => (
          <button
            key={spec.id}
            type="button"
            onClick={() => setSelectedId(spec.id)}
            className={`rounded-full px-3 py-1 text-xs font-medium border transition-colors ${
              selected?.id === spec.id
                ? 'bg-slate-900 text-white border-slate-900'
                : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-100'
            }`}
          >
            {spec.title}
          </button>
        ))}
      </div>

      {visibleRecommended.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {visibleRecommended.map((view) => (
            <span
              key={view}
              className="rounded-full bg-blue-50 border border-blue-100 px-2 py-0.5 text-[11px] font-medium text-blue-700"
            >
              {view}
            </span>
          ))}
        </div>
      )}

      {selected && (
        <div className="mt-3 rounded-xl border border-slate-200 bg-white p-3">
          <div className="mb-2">
            <div className="text-sm font-semibold text-slate-800">{selected.title}</div>
            {selected.description && (
              <div className="text-xs text-slate-500 mt-1">{selected.description}</div>
            )}
          </div>
          <div className="h-[320px]">
            <VChart spec={selected.spec} style={{ width: '100%', height: '100%' }} />
          </div>
        </div>
      )}
    </div>
  )
}
