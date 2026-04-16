import { Suspense, lazy, useState, useEffect, useRef } from 'react'
import { Send, Bot, User, Sparkles, Search, MessageCircle, FlaskConical, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { backendStatus, sendChatMessage, sendInterpretationQuery, sendResearchQueryStreaming, fetchChatStatus } from '../api/client'
import ResearchSessionPanel from './ResearchSessionPanel'

const AgentChart = lazy(() => import('./AgentChart'))
const ResearchChartsPanel = lazy(() => import('./ResearchChartsPanel'))
const VISUAL_QUERY_RE = /plot|chart|trend|visuali[sz]e|graph/i
const INTERPRETATION_QUERY_RE = /interpret|explain|read|meaning|what does|chart|trend|compare .*well|lee l-\d+|water supply|groundwater sources?|supply source|drinking water|aquifer.*supply|changes? in groundwater levels|30 years|which wells/i

/** Custom component overrides for ReactMarkdown (no @tailwindcss/typography). */
const markdownComponents = {
  h1: ({ children }) => <h1 className="text-base font-bold mt-3 mb-1">{children}</h1>,
  h2: ({ children }) => <h2 className="text-sm font-bold mt-3 mb-1">{children}</h2>,
  h3: ({ children }) => <h3 className="text-sm font-semibold mt-2 mb-0.5">{children}</h3>,
  p: ({ children }) => <p className="mb-1.5 leading-relaxed">{children}</p>,
  ul: ({ children }) => <ul className="list-disc pl-4 mb-1.5 space-y-0.5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-4 mb-1.5 space-y-0.5">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
      {children}
    </a>
  ),
}

/**
 * Try to extract a Recharts-ready chart payload from a text response.
 * The agent may embed a JSON block with chart_type / series / data.
 * Returns { text, chart } where chart is null or the parsed object.
 */
function extractChart(text) {
  if (!text) return { text, chart: null }

  // Look for a JSON block that contains "chart_type"
  const jsonBlockRe = /```json\s*([\s\S]*?)```/
  const match = text.match(jsonBlockRe)
  if (match) {
    try {
      const parsed = JSON.parse(match[1])
      if (parsed && parsed.chart_type && parsed.data) {
        const cleaned = text.replace(jsonBlockRe, '').trim()
        return { text: cleaned, chart: parsed }
      }
    } catch { /* not valid JSON, ignore */ }
  }

  // Also try if the entire response is JSON
  try {
    const parsed = JSON.parse(text)
    if (parsed && parsed.chart_type && parsed.data) {
      return { text: '', chart: parsed }
    }
  } catch { /* not JSON */ }

  return { text, chart: null }
}

function chartContextFromPayload(chart) {
  if (!chart) return null
  const siteIds = Array.isArray(chart.series)
    ? chart.series
        .map(series => String(series.key || ''))
        .filter(key => key && key !== 'avg' && !key.endsWith('_trend'))
    : []
  if (siteIds.length === 0) return null
  return {
    chart_id: chart.title || `${chart.chart_type || 'chart'}:${siteIds.join(',')}`,
    site_ids: [...new Set(siteIds)],
    chart_type: chart.chart_type || 'comparison',
    summary_metrics: {
      title: chart.title || '',
      summary: chart.explainability?.summary || '',
      insights: chart.insights || [],
      site_ids: [...new Set(siteIds)],
    },
  }
}

function turnHistoryFromMessages(messages) {
  return messages.slice(-4).map(message => ({
    role: message.role,
    content_preview: String(message.content || '').slice(0, 260),
    chart_id: message.chartContextRef?.chart_id || null,
  }))
}

const EXAMPLE_QUESTIONS = [
  "What groundwater sources does Estero use, and how have levels changed?",
  "Interpret the Estero groundwater chart for a sponsor.",
  "Which Lee County wells are changing fastest?",
  "Compare Lee L-581 and Lee L-588.",
]

const RESEARCH_EXAMPLES = [
  "What are the long-term trends for Biscayne Aquifer sites?",
  "Compare water levels in Miami-Dade vs Collier County over the last 5 years",
  "What does the literature say about saltwater intrusion in Southeast Florida?",
]

export default function ChatView({ selectedSite, onOpenWorkbench }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: "Welcome to Florida Aquifer Analysis. I can help answer questions about groundwater, irrigation, crops, and aquifers in Florida. Switch to Deep Research mode for multi-step investigations with source citations.",
      sources: [],
    }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [mode, setMode] = useState('chat') // 'chat' | 'research'
  const [agentStatus, setAgentStatus] = useState(null)
  const [backendState, setBackendState] = useState(() => backendStatus.getStatus())
  const [activeChartContext, setActiveChartContext] = useState(null)
  const messagesContainerRef = useRef(null)

  // Keep scrolling contained inside the chat transcript, not the outer page.
  useEffect(() => {
    const el = messagesContainerRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [messages])

  // Check agent status on mount
  useEffect(() => {
    fetchChatStatus()
      .then(setAgentStatus)
      .catch(() => setAgentStatus(null))
  }, [])

  useEffect(() => backendStatus.subscribe(setBackendState), [])

  const sendMessage = async (text = input, { chartContext } = {}) => {
    if (!text.trim()) return

    const priorMessages = messages
    const requestChartContext = chartContext || activeChartContext || null
    const turnHistory = turnHistoryFromMessages(priorMessages)
    const userMessage = { role: 'user', content: text }
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setLoading(true)

    try {
      if (mode === 'research') {
        // Deep Research mode — stream progress events so the user can see
        // the LLM working in real time instead of waiting in silence.

        // Insert the initial progress bubble.  We'll update its content in
        // place as each progress event arrives from the backend.
        const PROGRESS_ID = Date.now() // stable key to find the bubble later
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: 'Starting deep research...',
          isProgress: true,
          progressId: PROGRESS_ID,
          progressValue: 0,
          progressStartedAt: Date.now(),
          sessionId: '',
          researchPlan: null,
          budgetStatus: null,
          checkpoints: [],
          toolTrace: [],
        }])

        // onProgress updates the existing progress bubble in-place rather
        // than appending new messages, keeping the thread tidy.
        const handleProgress = (message, progress, snapshot) => {
          setMessages(prev => prev.map(m =>
            m.progressId === PROGRESS_ID
              ? { ...m, content: message, progressValue: progress }
              : m
          ).map(m =>
            m.progressId === PROGRESS_ID
              ? {
                  ...m,
                  sessionId: snapshot?.session_id || m.sessionId,
                  researchPlan: snapshot?.research_plan || m.researchPlan,
                  budgetStatus: snapshot?.budget_status || m.budgetStatus,
                  checkpoints: snapshot?.checkpoints || m.checkpoints,
                  toolTrace: snapshot?.tool_trace || m.toolTrace,
                }
              : m
          ))
        }

        const data = await sendResearchQueryStreaming(text, { onProgress: handleProgress })
        const reportRaw = data.report || data.response || 'Research complete — no report generated.'
        const { text: reportText } = extractChart(reportRaw)
        const answerBrief = data.answer_brief || data.interpretation_response?.interpretation || null
        const chart = data.chart || null
        const chartContextRef = chartContextFromPayload(chart)
        if (chartContextRef) setActiveChartContext(chartContextRef)

        // Swap out the progress bubble for the finished report.
        setMessages(prev => {
          const filtered = prev.filter(m => m.progressId !== PROGRESS_ID)
          const elapsedSeconds = Number.isFinite(data.elapsed_seconds)
            ? Math.round(data.elapsed_seconds)
            : 0
          return [...filtered, {
            role: 'assistant',
            content: answerBrief || reportText,
            rawContent: answerBrief && reportText && answerBrief.trim() !== reportText.trim() ? reportText : '',
            chart,
            chartContextRef,
            context: `Depth reached: ${data.depth_reached ?? 0} | Elapsed: ${elapsedSeconds}s`,
            sources: data.sources || [],
            sessionId: data.session_id || '',
            researchPlan: data.research_plan || null,
            budgetStatus: data.budget_status || null,
            checkpoints: data.checkpoints || [],
            toolTrace: data.tool_trace || [],
            recommendedViews: data.recommended_views || [],
            chartSpecs: data.chart_specs || [],
            insights: data.insights || [],
            claimCitations: data.claim_citations || [],
            citationSummary: data.citation_summary || null,
            // G5.9 — verdict data from the ClaimDisagreementEngine
            claimVerdicts: data.claim_verdicts || [],
            claimVerdictSummary: data.claim_verdict_summary || null,
            wells: data.wells || [],
            aquiferInfo: data.aquifer_info || null,
            divergentPairs: data.divergent_pairs || [],
            cohortRisk: data.cohort_risk_level || null,
            llmSynthesis: data.llm_synthesis || null,
            interpretationDetails: data.interpretation_details || null,
            hallucinationGuardrail: data.hallucination_guardrail || null,
            citationIntegrity: data.citation_integrity || null,
            requestedVisualization: VISUAL_QUERY_RE.test(text),
            mode: data.mode,
          }]
        })
      } else {
        // Quick chat mode
        const wantsInterpretation = INTERPRETATION_QUERY_RE.test(text)
        const data = wantsInterpretation
          ? await sendInterpretationQuery(text, {
              audience: 'general',
              useLlm: false,
              chartContext: requestChartContext,
              turnHistory,
            })
          : await sendChatMessage(text, {
              chartContext: requestChartContext,
              turnHistory,
            })
        const { text: replyText } = extractChart(data.response)
        const answerBrief = data.answer_brief || data.interpretation_response?.interpretation || data.llm_synthesis || null
        const chart = data.chart || null
        const chartContextRef = chartContextFromPayload(chart) || requestChartContext
        if (chartContextRef) setActiveChartContext(chartContextRef)

        setMessages(prev => [...prev, {
          role: 'assistant',
          content: answerBrief || replyText,
          rawContent: answerBrief && replyText && answerBrief.trim() !== replyText.trim() ? replyText : '',
          chart,
          chartContextRef,
          context: data.context,
          sources: data.sources || [],
          sessionId: data.session_id || '',
          researchPlan: data.research_plan || null,
          budgetStatus: data.budget_status || null,
          checkpoints: data.checkpoints || [],
          toolTrace: data.tool_trace || [],
          recommendedViews: data.recommended_views || [],
          chartSpecs: data.chart_specs || [],
          wells: data.wells || [],
          aquiferInfo: data.aquifer_info || null,
          divergentPairs: data.divergent_pairs || [],
          cohortRisk: data.cohort_risk_level || null,
          llmSynthesis: data.llm_synthesis || null,
          interpretationDetails: data.interpretation_details || null,
          hallucinationGuardrail: data.hallucination_guardrail || null,
          citationIntegrity: data.citation_integrity || null,
          interpretationResponse: data.interpretation_response || null,
          requestedVisualization: VISUAL_QUERY_RE.test(text),
          mode: data.mode,
          status: data.status,
        }])
      }
    } catch (error) {
      console.error('Chat error:', error)
      setMessages(prev => {
        // Remove any in-flight progress bubble (chat or research mode)
        const filtered = prev.filter(m => !m.isProgress)
        return [...filtered, {
          role: 'assistant',
          content: "Sorry, I couldn't process that request. Make sure the API server is running.",
          error: true,
        }]
      })
    } finally {
      setLoading(false)
    }
  }

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const examples = mode === 'research' ? RESEARCH_EXAMPLES : EXAMPLE_QUESTIONS

  return (
    <div className="flex h-[calc(100vh-120px)] min-h-[620px] max-h-[860px] flex-col bg-[linear-gradient(180deg,_rgba(248,250,252,0.92),_rgba(255,255,255,0.98))]">
      {/* Header */}
      <div className="border-b border-slate-200 bg-[radial-gradient(circle_at_top_left,_rgba(20,184,166,0.16),_transparent_24%),linear-gradient(135deg,_#0f172a,_#164e63)] p-5 text-white">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-2xl bg-white/10 p-2.5 ring-1 ring-white/10">
              <Bot className="w-6 h-6" />
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-[0.24em] text-teal-100/80">Groundwater Assistant</p>
              <h3 className="text-xl font-semibold">Ask about wells, aquifers, trends, and supply risk</h3>
              <p className="mt-1 flex items-center gap-1 text-sm text-teal-50/80">
                <Sparkles className="w-3 h-3" />
                {agentStatus?.agent_available
                  ? 'LLM-powered agent active'
                  : 'Rule-based mode (LLM agent unavailable)'}
              </p>
            </div>
          </div>

          {/* Mode Toggle */}
          <div className="flex overflow-hidden rounded-xl bg-white/10 text-sm ring-1 ring-white/10">
            <button
              onClick={() => setMode('chat')}
              className={`flex items-center gap-1 px-3 py-1.5 transition-colors ${
                mode === 'chat' ? 'bg-white/20 font-semibold' : 'hover:bg-white/10'
              }`}
            >
              <MessageCircle className="w-3.5 h-3.5" /> Chat
            </button>
            <button
              onClick={() => setMode('research')}
              className={`flex items-center gap-1 px-3 py-1.5 transition-colors ${
                mode === 'research' ? 'bg-white/20 font-semibold' : 'hover:bg-white/10'
              }`}
            >
              <Search className="w-3.5 h-3.5" /> Research
            </button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full bg-white/10 px-3 py-1.5 text-teal-50/85">
            {mode === 'chat' ? 'Fast answers for groundwater prompts' : 'Long-form, multi-step groundwater research'}
          </span>
          {selectedSite && (
            <span className="rounded-full bg-teal-400/15 px-3 py-1.5 text-teal-100">
              Current site: {selectedSite.name}
            </span>
          )}
        </div>
      </div>

      {backendState === 'down' && (
        <div className="border-b border-red-200 bg-red-50 px-5 py-3 text-sm text-red-700">
          <span className="font-medium">Backend unreachable</span> — check uvicorn on `:8000`.
        </div>
      )}

      {/* Messages */}
      <div
        ref={messagesContainerRef}
        className="min-h-0 flex-1 overscroll-contain overflow-y-auto bg-[linear-gradient(180deg,_rgba(248,250,252,0.65),_rgba(241,245,249,0.85))] p-4"
      >
        {selectedSite && (
          <div className="mb-4 rounded-2xl border border-teal-100 bg-teal-50/80 p-4 text-sm text-slate-700 shadow-sm">
            <div className="flex items-start gap-3">
              <div className="rounded-xl bg-white p-2 text-teal-700 shadow-sm">
                <FlaskConical className="h-4 w-4" />
              </div>
              <div>
                <p className="font-medium text-slate-900">Selected site context available</p>
                <p className="mt-1 leading-6 text-slate-600">
                  Ask about <span className="font-medium text-slate-800">{selectedSite.name}</span>, compare it to nearby wells, or switch to research mode for a cited report.
                </p>
              </div>
            </div>
          </div>
        )}

        <div className="space-y-4">
        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {msg.role === 'assistant' && (
              <div className="bg-blue-100 text-blue-600 p-2 rounded-full h-8 w-8 flex items-center justify-center flex-shrink-0">
                <Bot className="w-4 h-4" />
              </div>
            )}

            <div
              className={`max-w-[80%] rounded-lg p-3 ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : msg.error
                  ? 'bg-red-50 border border-red-200 text-red-800'
                  : msg.isProgress
                  ? 'bg-amber-50 border border-amber-200 text-amber-800'
                  : 'bg-white border border-slate-200 text-slate-800'
              }`}
            >
              <div className="text-sm leading-relaxed">
                <ReactMarkdown components={markdownComponents}>{msg.content}</ReactMarkdown>
              </div>

              {msg.rawContent && (
                <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <summary className="cursor-pointer text-xs font-medium text-slate-600">
                    Evidence report
                  </summary>
                  <div className="mt-2 max-h-80 overflow-y-auto pr-1 text-xs leading-relaxed text-slate-700">
                    <ReactMarkdown components={markdownComponents}>{msg.rawContent}</ReactMarkdown>
                  </div>
                </details>
              )}

              {(msg.isProgress || msg.researchPlan || msg.budgetStatus) && (
                <ResearchSessionPanel
                  sessionId={msg.sessionId}
                  progressValue={msg.progressValue}
                  progressStartedAt={msg.progressStartedAt}
                  live={Boolean(msg.isProgress)}
                  message={msg.content}
                  researchPlan={msg.researchPlan}
                  budgetStatus={msg.budgetStatus}
                  checkpoints={msg.checkpoints}
                  toolTrace={msg.toolTrace}
                />
              )}

              {/* Inline chart from agent visualization tools */}
              {msg.chart && (
                <div className="mt-3 -mx-1">
                  <Suspense fallback={<div className="h-[320px]" />}>
                    <AgentChart chartData={msg.chart} />
                  </Suspense>
                </div>
              )}

              {msg.interpretationResponse && (
                <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3">
                  <div className="text-xs font-medium text-emerald-800">
                    Interpretation Brief
                  </div>
                  {msg.interpretationResponse.interpretation && (
                    msg.interpretationResponse.interpretation !== msg.content && (
                      <p className="mt-1 text-sm leading-relaxed text-slate-800">
                        {msg.interpretationResponse.interpretation}
                      </p>
                    )
                  )}
                  {Array.isArray(msg.interpretationResponse.key_observations) && msg.interpretationResponse.key_observations.length > 0 && (
                    <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-slate-700">
                      {msg.interpretationResponse.key_observations.slice(0, 3).map((item, i) => (
                        <li key={i}>{item}</li>
                      ))}
                    </ul>
                  )}
                  {Array.isArray(msg.interpretationResponse.follow_up_questions) && msg.interpretationResponse.follow_up_questions.length > 0 && (
                    <div className="mt-2 border-t border-emerald-200 pt-2">
                      <p className="text-[11px] font-medium text-emerald-800">Ask Next</p>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        {msg.interpretationResponse.follow_up_questions.slice(0, 3).map((item, i) => (
                          <button
                            key={i}
                            type="button"
                            onClick={() => sendMessage(item, { chartContext: msg.chartContextRef })}
                            className="rounded-md border border-emerald-200 bg-white px-2 py-1 text-left text-[11px] text-emerald-900 hover:bg-emerald-100"
                          >
                            {item}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {msg.interpretationResponse.grounding_status && (
                    <div className="mt-2 text-[10px] text-slate-500">
                      USGS data: {msg.interpretationResponse.grounding_status.uses_usgs_data ? 'yes' : 'no'} · Chart context: {msg.interpretationResponse.grounding_status.uses_chart_context ? 'yes' : 'no'} · LLM: {msg.interpretationResponse.grounding_status.has_llm_synthesis ? 'grounded synthesis' : 'fast grounded mode'}
                    </div>
                  )}
                </div>
              )}

              {!msg.chart && msg.requestedVisualization && (
                <div className="mt-3 text-xs italic text-slate-400">
                  No time series available for this query.
                </div>
              )}

              {msg.chartSpecs && msg.chartSpecs.length > 0 && (
                <Suspense fallback={<div className="h-[320px]" />}>
                  <ResearchChartsPanel
                    chartSpecs={msg.chartSpecs}
                    recommendedViews={msg.recommendedViews || []}
                  />
                </Suspense>
              )}

              {msg.llmSynthesis && (
                <div className="mt-3 bg-cyan-50 border border-cyan-200 rounded-lg p-3">
                  <div className="text-xs text-cyan-700 font-medium mb-1">
                    Grounded LLM Chart Explanation
                  </div>
                  <div className="mb-2 text-[11px] text-slate-500">
                    The model explains deterministic USGS chart context; it does not create the measurements.
                  </div>
                  <div className="text-sm text-slate-800">
                    <ReactMarkdown components={markdownComponents}>{msg.llmSynthesis}</ReactMarkdown>
                  </div>
                </div>
              )}

              {(msg.interpretationDetails?.supply_interpretation || msg.interpretationResponse?.supply_interpretation) && (() => {
                const supply = msg.interpretationDetails?.supply_interpretation || msg.interpretationResponse?.supply_interpretation
                const units = supply?.supply_units || []
                return (
                  <details className="mt-3 rounded-lg border border-teal-200 bg-teal-50 p-3">
                    <summary className="cursor-pointer text-xs font-medium text-teal-800">
                      Supply source mapping
                    </summary>
                    <div className="mt-2 space-y-2 text-xs text-slate-700">
                      <p>
                        {supply.municipality} · {supply.utility}
                        {supply.confidence && <span className="text-slate-500"> · {supply.confidence}</span>}
                      </p>
                      {units.slice(0, 4).map((unit, i) => (
                        <div key={`${unit.zone}-${i}`} className="rounded-md bg-white p-2">
                          <div className="font-medium text-slate-800">
                            {unit.usage} · {unit.aquifer} / {unit.zone}
                          </div>
                          <div className="mt-1 text-slate-500">
                            {(unit.proxy_wells || []).length > 0
                              ? `Proxy wells: ${(unit.proxy_wells || []).map(w => w.name).filter(Boolean).slice(0, 4).join(', ')}`
                              : 'No matching proxy well in the loaded dataset.'}
                          </div>
                        </div>
                      ))}
                    </div>
                  </details>
                )
              })()}

              {msg.hallucinationGuardrail && !msg.hallucinationGuardrail.all_factual_claims_cited && (
                <div className="text-[10px] text-amber-500 mt-1">
                  Some claims are uncited
                  {msg.hallucinationGuardrail.has_llm_synthesis && ' · includes LLM synthesis'}
                </div>
              )}

              {msg.citationIntegrity && (
                <div className="mt-1 flex items-center gap-2 text-[10px]">
                  <span className={`px-1.5 py-0.5 rounded font-medium ${
                    msg.citationIntegrity.passed
                      ? 'bg-green-100 text-green-700'
                      : 'bg-amber-100 text-amber-700'
                  }`}>
                    Integrity: {msg.citationIntegrity.passed ? 'passed' : 'below threshold'}
                  </span>
                  <span className="text-slate-400">
                    {Math.round((msg.citationIntegrity.claim_citation_coverage || 0) * 100)}% claim · {Math.round((msg.citationIntegrity.section_citation_coverage || 0) * 100)}% section
                  </span>
                </div>
              )}

              {msg.context && (
                <p className="text-xs mt-2 opacity-70 border-t border-slate-200 pt-2">
                  {msg.context}
                </p>
              )}

              {msg.sources && msg.sources.length > 0 && (
                <div className="mt-2 pt-2 border-t border-slate-200">
                  <p className="text-xs text-slate-500">Sources:</p>
                  {msg.sources.map((src, i) => (
                    <span key={i} className="text-xs text-blue-600 mr-2">• {typeof src === 'string' ? src : src.url || JSON.stringify(src)}</span>
                  ))}
                </div>
              )}

              {msg.insights && msg.insights.length > 0 && (
                <details className="mt-2 pt-2 border-t border-slate-200">
                  <summary className="text-xs text-slate-500 cursor-pointer">
                    {msg.insights.length} research insight{msg.insights.length > 1 ? 's' : ''} — click to expand
                  </summary>
                  <ul className="mt-1 space-y-1">
                    {msg.insights.map((ins, i) => (
                      <li key={i} className="text-xs text-slate-600">
                        • {ins.content?.slice(0, 200)}{ins.content?.length > 200 ? '…' : ''}
                        {ins.confidence && <span className="ml-1 text-green-600">({Math.round(ins.confidence * 100)}% conf)</span>}
                      </li>
                    ))}
                  </ul>
                </details>
              )}

              {/* G5.9 — Verdict summary banner, shown whenever the research
                  agent returns claim_verdict_summary. One line of stats with
                  colour-coded counts so reviewers see conflict level at a glance. */}
              {msg.claimVerdictSummary && msg.claimVerdictSummary.total_claims > 0 && (
                <div className="mt-2 pt-2 border-t border-slate-200 flex flex-wrap items-center gap-2 text-xs">
                  <span className="text-slate-500 font-medium">Verdict:</span>
                  {/* Supported count — green */}
                  <span className="inline-flex items-center gap-1 bg-green-50 text-green-700 border border-green-200 px-2 py-0.5 rounded-full">
                    {msg.claimVerdictSummary.supported_claims} supported
                  </span>
                  {/* Contradicted count — red, only shown when >0 */}
                  {msg.claimVerdictSummary.contradicted_claims > 0 && (
                    <span className="inline-flex items-center gap-1 bg-red-50 text-red-700 border border-red-200 px-2 py-0.5 rounded-full">
                      {msg.claimVerdictSummary.contradicted_claims} contradicted
                    </span>
                  )}
                  {/* Insufficient evidence count — grey */}
                  {msg.claimVerdictSummary.insufficient_evidence_claims > 0 && (
                    <span className="inline-flex items-center gap-1 bg-slate-100 text-slate-500 border border-slate-200 px-2 py-0.5 rounded-full">
                      — {msg.claimVerdictSummary.insufficient_evidence_claims} insufficient
                    </span>
                  )}
                  {/* Contradicted rate warning — only shown when rate exceeds 15% */}
                  {msg.claimVerdictSummary.contradicted_claim_rate > 0.15 && (
                    <span className="text-red-600 font-medium">
                      {Math.round(msg.claimVerdictSummary.contradicted_claim_rate * 100)}% of claims conflict — see report below
                    </span>
                  )}
                </div>
              )}

              {/* Citations + per-claim verdict badges */}
              {(msg.citationSummary || (msg.claimCitations && msg.claimCitations.length > 0)) && (
                <details className="mt-2 pt-2 border-t border-slate-200">
                  <summary className="text-xs text-slate-500 cursor-pointer">
                    Citation coverage: {Math.round(((msg.citationSummary?.citation_coverage || 0) * 100))}% (
                    {msg.citationSummary?.cited_claims || 0}/{msg.citationSummary?.total_claims || msg.claimCitations?.length || 0} claims cited)
                  </summary>
                  <ul className="mt-1 space-y-1">
                    {(msg.claimCitations || []).map((claim, i) => {
                      // Look up the verdict for this claim_id so we can badge it.
                      const verdict = (msg.claimVerdicts || []).find(
                        v => v.claim_id === claim.claim_id
                      )?.verdict || 'insufficient_evidence'

                      // Colour map: supported → green, contradicted → red, else grey
                      const badgeStyle =
                        verdict === 'supported'
                          ? 'bg-green-100 text-green-700'
                          : verdict === 'contradicted'
                          ? 'bg-red-100 text-red-700'
                          : 'bg-slate-100 text-slate-500'

                      const badgeLabel =
                        verdict === 'supported' ? 'Supported'
                        : verdict === 'contradicted' ? 'Conflicted'
                        : 'Insufficient'

                      return (
                        <li key={claim.claim_id || i} className="text-xs text-slate-600 flex items-start gap-1.5">
                          {/* Verdict badge — coloured dot to the left of the claim */}
                          <span className={`mt-0.5 flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-semibold ${badgeStyle}`}>
                            {badgeLabel}
                          </span>
                          <span>
                            {claim.claim || 'Claim'}
                            {Array.isArray(claim.citations) && claim.citations.length > 0 && (
                              <span className="ml-1 text-blue-600">
                                [{claim.citations.map(c => c.url).filter(Boolean).slice(0, 2).join(', ')}]
                              </span>
                            )}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                </details>
              )}

              {msg.wells && msg.wells.length > 0 && (() => {
                // Group wells by aquifer for structured display
                const grouped = {}
                msg.wells.forEach(w => {
                  const key = w.aquifer || 'Unknown'
                  if (!grouped[key]) grouped[key] = []
                  grouped[key].push(w)
                })
                const aquiferNames = Object.keys(grouped)
                const hasMultipleAquifers = aquiferNames.length > 1

                return (
                  <details className="mt-2 pt-2 border-t border-slate-200">
                    <summary className="text-xs text-slate-500 cursor-pointer">
                      Well details — {msg.wells.length} monitoring site{msg.wells.length > 1 ? 's' : ''}
                      {hasMultipleAquifers && ` across ${aquiferNames.length} aquifer systems`}
                      {!hasMultipleAquifers && msg.aquiferInfo && (
                        <span className="ml-2 text-slate-400">
                          | {msg.aquiferInfo.name}
                          {msg.aquiferInfo.monitored_wells != null && ` (${msg.aquiferInfo.monitored_wells} wells monitored)`}
                        </span>
                      )}
                    </summary>
                    {aquiferNames.map(aqName => (
                      <div key={aqName} className="mt-2">
                        {hasMultipleAquifers && (
                          <div className="text-xs font-semibold text-slate-600 mb-1 px-1">
                            {aqName} ({grouped[aqName].length} well{grouped[aqName].length > 1 ? 's' : ''})
                          </div>
                        )}
                        <ul className="space-y-2">
                          {grouped[aqName].map((w) => {
                            const confined = w.confined
                            const badgeColor = confined ? 'bg-blue-100 text-blue-700' : 'bg-green-100 text-green-700'
                            const zoneRange = Array.isArray(w.aquifer_zone_depth_range_ft)
                              ? `${w.aquifer_zone_depth_range_ft[0]}–${w.aquifer_zone_depth_range_ft[1]} ft`
                              : null
                            const marginFt = w.saturation_margin_ft
                            const marginLabel = marginFt != null
                              ? marginFt >= 0
                                ? `${marginFt} ft above zone top`
                                : `${Math.abs(marginFt)} ft below zone top`
                              : null
                            return (
                              <li key={w.site_id} className="text-xs bg-slate-50 rounded p-2 space-y-0.5">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <a
                                    href={`https://waterdata.usgs.gov/monitoring-location/${w.site_id}/`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="font-medium text-blue-600 hover:underline"
                                  >
                                    {w.name}
                                  </a>
                                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${badgeColor}`}>
                                    {confined ? 'confined' : 'unconfined'}
                                  </span>
                                  {w.is_artesian && (
                                    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-cyan-100 text-cyan-700">
                                      artesian
                                    </span>
                                  )}
                                  <span className="text-slate-400">{w.county}</span>
                                </div>
                                <div className="text-slate-600">
                                  {w.aquifer_zone || w.aquifer}
                                  {w.well_depth_ft != null && ` · well depth ${w.well_depth_ft} ft`}
                                  {zoneRange && ` · zone ${zoneRange}`}
                                </div>
                                {marginLabel && (
                                  <div className={`text-[10px] font-medium ${marginFt < 0 ? 'text-red-600' : 'text-slate-500'}`}>
                                    Head margin: {marginLabel}
                                  </div>
                                )}
                                {w.aquifer_description && (
                                  <div className="text-slate-400 italic leading-snug">
                                    {w.aquifer_description.length > 120
                                      ? w.aquifer_description.slice(0, 120) + '…'
                                      : w.aquifer_description}
                                  </div>
                                )}
                              </li>
                            )
                          })}
                        </ul>
                      </div>
                    ))}
                  </details>
                )
              })()}

              {msg.divergentPairs && msg.divergentPairs.length > 0 && (
                <details className="mt-2 pt-2 border-t border-slate-200">
                  <summary className="text-xs text-slate-500 cursor-pointer">
                    {msg.divergentPairs.length} divergent well pair{msg.divergentPairs.length > 1 ? 's' : ''} detected
                    {msg.cohortRisk && (
                      <span className={`ml-2 px-1.5 py-0.5 rounded text-[10px] font-medium ${
                        msg.cohortRisk === 'high' ? 'bg-red-100 text-red-700'
                        : msg.cohortRisk === 'moderate' ? 'bg-amber-100 text-amber-700'
                        : 'bg-green-100 text-green-700'
                      }`}>
                        {msg.cohortRisk} risk
                      </span>
                    )}
                  </summary>
                  <ul className="mt-1 space-y-1">
                    {msg.divergentPairs.slice(0, 3).map((pair, i) => (
                      <li key={i} className="text-xs bg-orange-50 border border-orange-100 rounded p-1.5">
                        <span className="text-red-600 font-medium">{pair.site_a?.name}</span>
                        <span className="text-slate-500">
                          {' '}({pair.site_a?.trend}, {pair.site_a?.annual_change_ft_yr > 0 ? '+' : ''}{pair.site_a?.annual_change_ft_yr} ft/yr)
                        </span>
                        <span className="text-slate-400 mx-1">vs</span>
                        <span className="text-green-600 font-medium">{pair.site_b?.name}</span>
                        <span className="text-slate-500">
                          {' '}({pair.site_b?.trend}, {pair.site_b?.annual_change_ft_yr > 0 ? '+' : ''}{pair.site_b?.annual_change_ft_yr} ft/yr)
                        </span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}

              {onOpenWorkbench && msg.wells && msg.wells.length > 0 && (
                <div className="mt-2 pt-2 border-t border-slate-200">
                  <button
                    type="button"
                    onClick={() => onOpenWorkbench({
                      siteIds: msg.wells.map((well) => well.site_id).filter(Boolean).slice(0, 8),
                      sourceLabel: msg.mode || 'assistant',
                    })}
                    className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-100"
                  >
                    <FlaskConical className="h-3.5 w-3.5" />
                    Open in Workbench
                  </button>
                </div>
              )}

              {msg.mode && (
                <div className="mt-2 flex items-center gap-1 text-xs text-slate-400">
                  {msg.mode === 'agent' && 'Agent'}
                  {msg.mode === 'deep_research' && 'Deep Research'}
                  {msg.mode === 'fallback' && 'Location Analysis'}
                  {msg.mode === 'site_fallback' && 'Site Analysis'}
                  {msg.mode === 'aquifer_fallback' && 'Aquifer Analysis'}
                  {msg.mode === 'network_fallback' && 'Network Analysis'}
                  {msg.mode === 'chart_interpreter' && 'Chart Interpreter'}
                  {msg.mode === 'interpret_chart_interpreter' && 'Chart Interpreter'}
                </div>
              )}
            </div>

            {msg.role === 'user' && (
              <div className="bg-slate-200 text-slate-600 p-2 rounded-full h-8 w-8 flex items-center justify-center flex-shrink-0">
                <User className="w-4 h-4" />
              </div>
            )}
          </div>
        ))}
        </div>

        {loading && !messages.some(m => m.isProgress) && (
          <div className="flex gap-3">
            <div className="bg-blue-100 text-blue-600 p-2 rounded-full h-8 w-8 flex items-center justify-center">
              <Bot className="w-4 h-4" />
            </div>
            <div className="bg-white border border-slate-200 rounded-lg p-3">
              <div className="flex gap-1">
                <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Example Questions */}
      <div className="border-t border-slate-200 bg-white/90 p-4">
        <p className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">
          {mode === 'research' ? 'Research examples:' : 'Try asking:'}
        </p>
        <div className="flex flex-wrap gap-2">
          {examples.slice(0, 3).map((q, i) => (
            <button
              key={i}
              onClick={() => sendMessage(q)}
              className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-700 transition-colors hover:border-teal-200 hover:bg-teal-50 hover:text-teal-800"
            >
              {q}
            </button>
          ))}
          {selectedSite && (
            <button
              onClick={() => sendMessage(`Summarize groundwater conditions at ${selectedSite.name}.`)}
              className="rounded-full border border-teal-200 bg-teal-50 px-3 py-1.5 text-xs text-teal-800 transition-colors hover:bg-teal-100"
            >
              Summarize {selectedSite.name}
            </button>
          )}
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-slate-200 bg-white/95 p-4">
        {activeChartContext && mode === 'chat' && (
          <div className="mb-2 inline-flex max-w-full items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs text-emerald-800">
            <span className="truncate">In context: {activeChartContext.summary_metrics?.title || activeChartContext.chart_id}</span>
            <button
              type="button"
              onClick={() => setActiveChartContext(null)}
              className="rounded p-0.5 text-emerald-700 hover:bg-emerald-100"
              aria-label="Clear chart context"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        )}
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder={
              mode === 'research'
                ? 'Ask a deep-research question with a site, county, or aquifer focus…'
                : 'Ask about groundwater levels, aquifers, well depth, irrigation, or supply risk…'
            }
            className="flex-1 rounded-2xl border border-slate-300 bg-slate-50 px-4 py-2.5 text-sm shadow-inner focus:border-transparent focus:outline-none focus:ring-2 focus:ring-teal-500"
            disabled={loading}
          />
          <button
            onClick={() => sendMessage()}
            disabled={loading || !input.trim()}
            className={`${
              mode === 'research'
                ? 'bg-teal-700 hover:bg-teal-800'
                : 'bg-slate-900 hover:bg-teal-700'
            } flex items-center gap-2 rounded-2xl px-4 py-2 text-white transition-colors disabled:bg-slate-300`}
          >
            {mode === 'research' ? <Search className="w-4 h-4" /> : <Send className="w-4 h-4" />}
          </button>
        </div>
        <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-400">
          <span>Tip: include a county, well name, site ID, or aquifer for more grounded answers.</span>
          {selectedSite && mode === 'chat' && (
            <button
              onClick={() => setInput(`Compare ${selectedSite.name} to nearby wells in ${selectedSite.county} County.`)}
              className="text-teal-700 hover:text-teal-800"
            >
              Use selected site as a starting prompt
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
