import { useEffect, useState } from 'react'

function formatBudgetValue(value, suffix = '') {
  if (value == null || Number.isNaN(value)) return '—'
  return `${value}${suffix}`
}

export default function ResearchSessionPanel({
  sessionId,
  progressValue,
  progressStartedAt,
  live = false,
  message,
  researchPlan,
  budgetStatus,
  checkpoints = [],
  toolTrace = [],
}) {
  const [liveElapsedSeconds, setLiveElapsedSeconds] = useState(0)

  useEffect(() => {
    if (!live || !progressStartedAt) {
      setLiveElapsedSeconds(0)
      return
    }

    const updateElapsed = () => {
      setLiveElapsedSeconds(Math.max(0, Math.round((Date.now() - progressStartedAt) / 1000)))
    }

    updateElapsed()
    const intervalId = window.setInterval(updateElapsed, 1000)
    return () => window.clearInterval(intervalId)
  }, [live, progressStartedAt])

  const planTools = researchPlan?.recommended_tools || []
  const planQuestions = researchPlan?.sub_questions || []
  const visibleCheckpoints = checkpoints.slice(-4).reverse()
  const visibleTrace = toolTrace.slice(-5).reverse()
  const elapsedSeconds = Math.round(
    budgetStatus?.elapsed_seconds ?? (live ? liveElapsedSeconds : 0)
  )
  const progressPercent = typeof progressValue === 'number' ? Math.round(progressValue * 100) : null
  const phaseLabel = (budgetStatus?.status || '').replaceAll('_', ' ')

  return (
    <div className={`mt-3 rounded-xl border p-3 ${
      live ? 'border-amber-200 bg-amber-50/80' : 'border-slate-200 bg-slate-50'
    }`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Research Session
          </div>
          <div className="text-sm font-semibold text-slate-800">
            {researchPlan?.main_question || message || 'Research run'}
          </div>
          {sessionId && <div className="text-[11px] text-slate-500 mt-0.5">Session: {sessionId}</div>}
        </div>
        {budgetStatus?.status && (
          <span className="rounded-full bg-white px-2 py-1 text-[11px] font-medium text-slate-600 border border-slate-200">
            {phaseLabel}
          </span>
        )}
      </div>

      {live && typeof progressValue === 'number' && (
        <div className="mt-3">
          <div className="mb-1 flex items-center justify-between text-[11px] text-amber-700">
            <span>{message || 'Research in progress'}</span>
            <span className="font-semibold">{progressPercent}%</span>
          </div>
          <div className="h-2 rounded-full bg-amber-100 overflow-hidden">
            <div
              className="h-full rounded-full bg-amber-500 transition-all duration-500"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>
      )}

      <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-2">
        <div className="rounded-lg bg-white border border-slate-200 p-2">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">Depth</div>
          <div className="text-sm font-semibold text-slate-800">
            {formatBudgetValue(budgetStatus?.depth_reached)} / {formatBudgetValue(budgetStatus?.max_depth)}
          </div>
        </div>
        <div className="rounded-lg bg-white border border-slate-200 p-2">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">Insights</div>
          <div className="text-sm font-semibold text-slate-800">
            {formatBudgetValue(budgetStatus?.insights_gathered)}
          </div>
        </div>
        <div className="rounded-lg bg-white border border-slate-200 p-2">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">Web Searches</div>
          <div className="text-sm font-semibold text-slate-800">
            {formatBudgetValue(budgetStatus?.web_searches_used)} / {formatBudgetValue(budgetStatus?.web_searches_max)}
          </div>
        </div>
        <div className="rounded-lg bg-white border border-slate-200 p-2">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">Elapsed</div>
          <div className="text-sm font-semibold text-slate-800">
            {formatBudgetValue(elapsedSeconds, 's')}
          </div>
        </div>
      </div>

      {(planQuestions.length > 0 || planTools.length > 0) && (
        <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
          {planQuestions.length > 0 && (
            <div className="rounded-lg bg-white border border-slate-200 p-3">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-2">
                Plan
              </div>
              <ul className="space-y-1 text-xs text-slate-600">
                {planQuestions.slice(0, 4).map((question, index) => (
                  <li key={index}>{question}</li>
                ))}
              </ul>
            </div>
          )}
          {planTools.length > 0 && (
            <div className="rounded-lg bg-white border border-slate-200 p-3">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-2">
                Recommended Tools
              </div>
              <div className="flex flex-wrap gap-1.5">
                {planTools.map((tool) => (
                  <span
                    key={tool}
                    className="rounded-full bg-blue-50 border border-blue-100 px-2 py-0.5 text-[11px] font-medium text-blue-700"
                  >
                    {tool}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {(visibleCheckpoints.length > 0 || visibleTrace.length > 0) && (
        <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
          {visibleCheckpoints.length > 0 && (
            <div className="rounded-lg bg-white border border-slate-200 p-3">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-2">
                Checkpoints
              </div>
              <div className="space-y-2">
                {visibleCheckpoints.map((checkpoint) => (
                  <div key={checkpoint.checkpoint_id} className="text-xs text-slate-600">
                    <div className="font-medium text-slate-700">{checkpoint.summary}</div>
                    <div className="text-[11px] text-slate-400">
                      {checkpoint.stage} · depth {checkpoint.depth}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {visibleTrace.length > 0 && (
            <div className="rounded-lg bg-white border border-slate-200 p-3">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-2">
                Tool Trace
              </div>
              <div className="space-y-2">
                {visibleTrace.map((event, index) => (
                  <div key={`${event.tool}-${event.timestamp}-${index}`} className="text-xs text-slate-600">
                    <div className="font-medium text-slate-700">
                      {event.tool} <span className="text-slate-400">· {event.status}</span>
                    </div>
                    {event.details?.query && (
                      <div className="text-[11px] text-slate-500">{event.details.query}</div>
                    )}
                    {event.details?.summary && (
                      <div className="text-[11px] text-slate-500">{event.details.summary}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
