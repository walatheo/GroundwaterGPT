import { Suspense, lazy, useState, useEffect, useRef } from 'react'
import { Send, Bot, User, Sparkles, MessageCircle, FlaskConical, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import {
  backendStatus,
  sendChatMessage,
  sendInterpretationQuery,
  sendResearchQueryStreaming,
  fetchChatStatus,
  sendLearnerEvent,
} from '../api/client'
import ResearchSessionPanel from './ResearchSessionPanel'

const AgentChart = lazy(() => import('./AgentChart'))
const ResearchChartsPanel = lazy(() => import('./ResearchChartsPanel'))
const VISUAL_QUERY_RE = /plot|chart|trend|visuali[sz]e|graph/i
const INTERPRETATION_QUERY_RE = /interpret|explain|read|meaning|what does|chart|compare .*well|lee l-\d+|which wells?|fastest|highlighted|cohort|diverge|proxy/i
const CHART_FOLLOWUP_RE = /which wells?|fastest|highlighted|cohort|average|trend line|diverge|divergent|compare|this chart|the chart|on the chart|using the chart|what should/i
const WELL_REFERENCE_RE = /\b(?:[a-z]{1,3}[\s-]?\d{3,5}|\d{15})\b/i
const EXPLICIT_CHART_REFERENCE_RE = /\b(this chart|the chart|on the chart|using the chart|highlighted|cohort|trend line|dataset)\b/i
const ENABLE_LLM_INTERPRETATION = String(import.meta.env.VITE_ENABLE_LLM_INTERPRETATION || '').toLowerCase() === 'true'
const SHOWCASE_MODE = ['1', 'true', 'yes', 'on'].includes(
  String(import.meta.env.VITE_GROUNDWATER_SHOWCASE_MODE || '').toLowerCase()
)
const REQUEST_LLM_INTERPRETATION = ENABLE_LLM_INTERPRETATION

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

function llmGroundingLabel(grounding) {
  if (!grounding?.has_llm_synthesis) return 'fast grounded mode'
  const provider = grounding.llm_provider || ''
  const model = grounding.llm_model || ''
  const modelLabel = [provider, model].filter(Boolean).join(' ')
  return modelLabel ? `grounded synthesis (${modelLabel})` : 'grounded synthesis'
}

function siteIdsFromMessage(message) {
  const ids = []
  const add = (value) => {
    const id = String(value || '').trim()
    if (id && id !== 'avg' && !id.endsWith('_trend') && !ids.includes(id)) ids.push(id)
  }
  message.chartContextRef?.site_ids?.forEach(add)
  message.chart?.series?.forEach(series => add(series.key))
  message.wells?.forEach(well => add(well.site_id || well.id))
  return ids.slice(0, 12)
}

function chartContextFromMessage(message) {
  const siteIds = siteIdsFromMessage(message)
  if (siteIds.length === 0) return null
  const title =
    message.chartContextRef?.summary_metrics?.title
    || message.chartContextRef?.chart_id
    || message.chart?.title
    || 'Recent groundwater context'
  return {
    chart_id: title,
    site_ids: siteIds,
    chart_type: message.chart?.chart_type || 'conversation_context',
    summary_metrics: {
      title,
      summary: message.chart?.explainability?.summary || '',
      insights: message.chart?.insights || [],
      site_ids: siteIds,
    },
  }
}

function turnHistoryFromMessages(messages) {
  return messages.slice(-4).map(message => {
    const context = chartContextFromMessage(message)
    const wells = Array.isArray(message.wells)
      ? message.wells.slice(0, 8).map(well => ({
          site_id: well.site_id || well.id || null,
          name: well.name || '',
          aquifer: well.aquifer || '',
          county: well.county || '',
        }))
      : []
    return {
      role: message.role,
      content_preview: String(message.content || '').slice(0, 260),
      mode: message.mode || '',
      chart_id: context?.chart_id || null,
      site_ids: context?.site_ids || [],
      wells,
      aquifer: message.aquiferInfo?.name || wells[0]?.aquifer || '',
      cohort_risk_level: message.cohortRisk || '',
      question_intent: message.questionIntent || '',
      direct_answer: String(message.directAnswer || '').slice(0, 500),
    }
  })
}

function shouldReuseActiveChartContext(text, activeChartContext, { forceInterpretation = false } = {}) {
  if (!activeChartContext) return false
  if (forceInterpretation) return true
  if (EXPLICIT_CHART_REFERENCE_RE.test(text)) return true
  if (WELL_REFERENCE_RE.test(text)) return false
  return CHART_FOLLOWUP_RE.test(text) || VISUAL_QUERY_RE.test(text)
}

function unitMeanRate(unit) {
  const trendSummary = unit?.trend_summary
  if (Number.isFinite(trendSummary?.mean_annual_change)) return trendSummary.mean_annual_change
  const proxies = unit?.proxy_wells || []
  if (proxies.length === 0) return null
  const rates = proxies
    .map(well => Number(well.annual_change_ft_yr))
    .filter(Number.isFinite)
  if (rates.length === 0) return null
  return rates.reduce((sum, rate) => sum + rate, 0) / rates.length
}

function buildContextualFollowUps(msg) {
  const questions = []
  const supply = msg.interpretationDetails?.supply_interpretation || msg.interpretationResponse?.supply_interpretation
  const units = supply?.supply_units || []

  if (units.length > 0) {
    const primaryUnit = units.find(unit => unit.usage === 'primary') || units[0]
    const rankedUnits = units
      .map(unit => ({ unit, rate: unitMeanRate(unit) }))
      .filter(item => Number.isFinite(item.rate))
      .sort((a, b) => a.rate - b.rate)
    questions.push(`Which proxy wells represent the ${primaryUnit.zone} supply unit?`)
    if (rankedUnits[0]?.unit?.zone) {
      questions.push(`Why is ${rankedUnits[0].unit.zone} the most stressed supply unit in this dataset?`)
    }
    questions.push('What caveats should I say before using this as a supply-risk claim?')
  }

  if (msg.chartContextRef || msg.chart) {
    questions.push('Which wells on this chart are changing fastest, and what are their rates?')
    if (Array.isArray(msg.divergentPairs) && msg.divergentPairs.length > 0) {
      const pair = msg.divergentPairs[0]
      const a = pair.site_a?.name
      const b = pair.site_b?.name
      if (a && b) questions.push(`Why do ${a} and ${b} diverge on this chart?`)
    } else {
      questions.push('Do the shallow and deep aquifer wells diverge on this chart?')
    }
    questions.push('What does the cohort average mean for these monitored wells?')
  }

  if (Array.isArray(msg.wells) && msg.wells.length >= 2) {
    questions.push('Explain the decline using these wells.')
    questions.push('Which well is changing fastest?')
    questions.push('What caveats should I mention?')
    const [first, second] = msg.wells
    if (first?.name && second?.name) {
      questions.push(`Compare ${first.name} and ${second.name} using the chart and well metadata.`)
    }
  }

  const backendQuestions = msg.interpretationResponse?.follow_up_questions || []
  questions.push(
    ...backendQuestions.filter(question =>
      /chart|wells?|cohort|aquifer|supply|proxy|trend|management/i.test(question)
    )
  )

  const seen = new Set()
  return questions
    .map(question => String(question || '').trim())
    .filter(question => question && !seen.has(question) && seen.add(question))
    .slice(0, 3)
}

function backendFollowUpGroups(msg) {
  const rawGroups = msg.interpretationResponse?.follow_up_groups || msg.followUpGroups || []
  if (!Array.isArray(rawGroups)) return []
  return rawGroups
    .map(group => {
      const label = String(group?.label || '').trim()
      const items = Array.isArray(group?.questions)
        ? group.questions
            .map(question => String(question || '').trim())
            .filter(Boolean)
            .slice(0, 2)
        : []
      if (!label || items.length === 0) return null
      return { label, items }
    })
    .filter(Boolean)
}

function buildGroupedFollowUps(msg) {
  const backendGroups = backendFollowUpGroups(msg)
  if (backendGroups.length > 0) return backendGroups

  const groups = [
    { label: 'Understand this', items: [] },
    { label: 'Compare wells', items: [] },
    { label: 'Check the caveat', items: [] },
    { label: 'What would strengthen this interpretation?', items: [] },
  ]
  const pushToGroup = (label, question) => {
    const group = groups.find(item => item.label === label)
    if (group && question && !group.items.includes(question) && group.items.length < 2) {
      group.items.push(question)
    }
  }

  for (const question of buildContextualFollowUps(msg)) {
    const lower = question.toLowerCase()
    if (/compare|diverge|shallow|deep/.test(lower)) {
      pushToGroup('Compare wells', question)
    } else if (/caveat|outside data|management claim|test a cause|confirm|strengthen/.test(lower)) {
      pushToGroup('Check the caveat', question)
    } else if (/what would|strengthen/.test(lower)) {
      pushToGroup('What would strengthen this interpretation?', question)
    } else {
      pushToGroup('Understand this', question)
    }
  }

  if (groups.find(group => group.label === 'What would strengthen this interpretation?')?.items.length === 0) {
    pushToGroup('What would strengthen this interpretation?', 'What outside data would strengthen this interpretation?')
  }
  return groups.filter(group => group.items.length > 0)
}

function resolveNextGoal(msg) {
  return String(
    msg.interpretationResponse?.next_goal
      || msg.nextGoal
      || ''
  ).trim()
}

function numericSourceLabel(source) {
  const labels = {
    annual_change_ft_yr: 'annual rate',
    mean_annual_change_ft_yr: 'cohort mean annual rate',
    net_change_ft: 'net change',
    latest_depth_to_water_ft: 'latest depth-to-water',
    well_depth_ft: 'well depth',
    record_years: 'record length',
  }
  return labels[source] || source
}

function formatSigned(value, digits = 3) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 'n/a'
  return `${numeric > 0 ? '+' : ''}${numeric.toFixed(digits)}`
}

function buildAnalyticalDepth(msg) {
  const interpretation = msg.interpretationResponse || {}
  const details = msg.interpretationDetails || interpretation.interpretation_details || {}
  const numericClaims = Array.isArray(interpretation.numeric_claims)
    ? interpretation.numeric_claims
    : []
  const observations = Array.isArray(interpretation.key_observations)
    ? interpretation.key_observations
    : []
  const answerRelevantObservations = Array.isArray(interpretation.answer_relevant_observations)
    ? interpretation.answer_relevant_observations
    : []
  const comparisonGroups = interpretation.comparison_groups || null
  const largestGap = interpretation.largest_gap || null
  const groundwaterConcepts = Array.isArray(interpretation.groundwater_concepts)
    ? interpretation.groundwater_concepts
    : []
  const meaningBrief = interpretation.meaning_brief || null
  const interpretiveFindings = Array.isArray(interpretation.interpretive_findings)
    ? interpretation.interpretive_findings
    : []
  const possibleDrivers = Array.isArray(interpretation.possible_drivers)
    ? interpretation.possible_drivers
    : []
  const evidenceNeeded = Array.isArray(interpretation.evidence_needed)
    ? interpretation.evidence_needed
    : []
  const managementImplications = Array.isArray(interpretation.management_implications)
    ? interpretation.management_implications
    : []
  const confidenceNotes = Array.isArray(interpretation.confidence_notes)
    ? interpretation.confidence_notes
    : []
  const limits = Array.isArray(interpretation.limits) ? interpretation.limits : []
  const aquiferSummaries = Array.isArray(details.aquifer_summaries)
    ? details.aquifer_summaries
    : Array.isArray(interpretation.aquifer_summaries)
      ? interpretation.aquifer_summaries
    : []
  const supplyUnits = details.supply_interpretation?.supply_units || interpretation.supply_interpretation?.supply_units || []
  const guardrailFlags = interpretation.guardrail_flags || []
  const learnerBrief = interpretation.learner_brief || null
  const termsToKnow = Array.isArray(interpretation.terms_to_know)
    ? interpretation.terms_to_know
    : []
  const misconceptionsToAvoid = Array.isArray(interpretation.misconceptions_to_avoid)
    ? interpretation.misconceptions_to_avoid
    : []
  const reasoningTrace = Array.isArray(interpretation.reasoning_trace)
    ? interpretation.reasoning_trace
    : Array.isArray(details.reasoning_trace)
      ? details.reasoning_trace
    : []
  const reasoningSource = interpretation.reasoning_source || details.reasoning_source || 'deterministic'
  const langgraphTrace = Array.isArray(interpretation.langgraph_trace)
    ? interpretation.langgraph_trace
    : Array.isArray(details.langgraph_trace)
      ? details.langgraph_trace
    : []

  if (
    numericClaims.length === 0 &&
    observations.length === 0 &&
    answerRelevantObservations.length === 0 &&
    groundwaterConcepts.length === 0 &&
    !meaningBrief &&
    interpretiveFindings.length === 0 &&
    possibleDrivers.length === 0 &&
    evidenceNeeded.length === 0 &&
    managementImplications.length === 0 &&
    confidenceNotes.length === 0 &&
    limits.length === 0 &&
    aquiferSummaries.length === 0 &&
    supplyUnits.length === 0 &&
    !comparisonGroups &&
    !msg.cohortRisk &&
    !learnerBrief &&
    termsToKnow.length === 0 &&
    misconceptionsToAvoid.length === 0 &&
    reasoningTrace.length === 0
  ) {
    return null
  }

  return {
    numericClaims,
    observations: answerRelevantObservations.length > 0 ? answerRelevantObservations : observations,
    rawObservations: observations,
    comparisonGroups,
    largestGap,
    groundwaterConcepts,
    meaningBrief,
    interpretiveFindings,
    possibleDrivers,
    evidenceNeeded,
    managementImplications,
    confidenceNotes,
    limits,
    aquiferSummaries,
    supplyUnits,
    guardrailFlags,
    learnerBrief,
    termsToKnow,
    misconceptionsToAvoid,
    reasoningTrace,
    reasoningSource,
    langgraphTrace,
    cohortRisk: msg.cohortRisk || details.risk_level || null,
    grounding: interpretation.grounding_status || null,
  }
}

function makeMessageId() {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

const EXAMPLE_QUESTIONS = [
  "What groundwater sources does Estero use, and how have levels changed?",
  "Interpret the Estero groundwater chart for a sponsor.",
  "Which Lee County wells are changing fastest?",
  "Compare Lee L-581 and Lee L-588.",
]

export default function ChatView({ selectedSite, onOpenWorkbench, fullScreen = false }) {
  const [messages, setMessages] = useState([
    {
      id: makeMessageId(),
      role: 'assistant',
      content: "Welcome to Florida Aquifer Analysis. I can answer groundwater questions with USGS-backed wells, charts, citations, and grounded interpretation. Ask about a location, aquifer, well, trend, or supply risk.",
      sources: [],
    }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [mode] = useState('chat') // Sponsor demo locks the visible chat surface to grounded chat.
  const [agentStatus, setAgentStatus] = useState(null)
  const [backendState, setBackendState] = useState(() => backendStatus.getStatus())
  const [activeChartContext, setActiveChartContext] = useState(null)
  const messagesEndRef = useRef(null)
  const hasMountedRef = useRef(false)

  const logLearnerEvent = async (event) => {
    try {
      await sendLearnerEvent(event)
    } catch (error) {
      console.warn('Learner event failed', error)
    }
  }

  // In full-screen chat the transcript is the single scroll owner; otherwise use page scroll.
  useEffect(() => {
    if (!hasMountedRef.current) {
      hasMountedRef.current = true
      return
    }
    window.requestAnimationFrame(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    })
  }, [messages])

  // Check agent status on mount
  useEffect(() => {
    fetchChatStatus()
      .then(setAgentStatus)
      .catch(() => setAgentStatus(null))
  }, [])

  useEffect(() => backendStatus.subscribe(setBackendState), [])

  const sendMessage = async (text = input, { chartContext, forceInterpretation = false } = {}) => {
    if (!text.trim()) return

    const priorMessages = messages
    const explicitChartContext = chartContext || null
    const shouldUseActiveChartContext = shouldReuseActiveChartContext(
      text,
      activeChartContext,
      { forceInterpretation }
    )
    const requestChartContext = explicitChartContext || (shouldUseActiveChartContext ? activeChartContext : null)
    const turnHistory = turnHistoryFromMessages(priorMessages)
    const userMessage = { id: makeMessageId(), role: 'user', content: text }
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
          id: makeMessageId(),
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
            id: makeMessageId(),
            role: 'assistant',
            content: answerBrief || reportText,
            rawContent: answerBrief && reportText && answerBrief.trim() !== reportText.trim() ? reportText : '',
            questionAsked: text,
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
            nextGoal: data.next_goal || '',
            followUpGroups: data.follow_up_groups || [],
            followUpQuestions: data.follow_up_questions || [],
            progressionSource: data.progression_source || '',
            requestedVisualization: VISUAL_QUERY_RE.test(text) && data.mode !== 'chart_interpreter',
            mode: data.mode,
          }]
        })
      } else {
        // Quick chat mode
        const wantsInterpretation = (
          forceInterpretation
          || INTERPRETATION_QUERY_RE.test(text)
          || Boolean(
            requestChartContext
            && (
              EXPLICIT_CHART_REFERENCE_RE.test(text)
              || (!WELL_REFERENCE_RE.test(text) && CHART_FOLLOWUP_RE.test(text))
            )
          )
        )
        const data = wantsInterpretation
          ? await sendInterpretationQuery(text, {
              audience: 'general',
              useLlm: REQUEST_LLM_INTERPRETATION,
              chartContext: requestChartContext,
              turnHistory,
            })
          : await sendChatMessage(text, {
              chartContext: requestChartContext,
              turnHistory,
              allowLlmSynthesis: false,
              ...(VISUAL_QUERY_RE.test(text) || Boolean(requestChartContext) ? { includeChart: true } : {}),
            })
        const { text: replyText } = extractChart(data.response)
        // Canonical contract first: grounded_answer.direct_answer is the
        // backend's product-level reply. Legacy fields are fallbacks for
        // payloads from paths that haven't been stamped yet.
        const groundedAnswer = data.grounded_answer || null
        const interpretationDirect = data.interpretation_response?.direct_answer || ''
        const directFromContract = groundedAnswer?.direct_answer || ''
        const answerBrief = interpretationDirect
          || directFromContract
          || data.answer_brief
          || data.interpretation_response?.interpretation
          || null
        const chart = data.chart || null
        const chartContextRef = chartContextFromPayload(chart) || requestChartContext
        if (chartContextRef) setActiveChartContext(chartContextRef)

        setMessages(prev => [...prev, {
          id: makeMessageId(),
          role: 'assistant',
          content: answerBrief || replyText,
          rawContent: answerBrief && replyText && answerBrief.trim() !== replyText.trim() ? replyText : '',
          groundedAnswer,
          answerType: data.answer_type || '',
          groundingStatus: data.grounding_status || '',
          routeMode: data.route_mode || '',
          questionAsked: text,
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
          nextGoal: data.next_goal || (data.interpretation_response || {}).next_goal || '',
          followUpGroups: data.follow_up_groups || (data.interpretation_response || {}).follow_up_groups || [],
          followUpQuestions: data.follow_up_questions || (data.interpretation_response || {}).follow_up_questions || [],
          progressionSource: data.progression_source || (data.interpretation_response || {}).progression_source || '',
          questionIntent: (data.interpretation_response || {}).question_intent || '',
          directAnswer: (data.interpretation_response || {}).direct_answer
            || '',
          requestedVisualization: (
            VISUAL_QUERY_RE.test(text)
            && data.mode !== 'chart_interpreter'
            && !data.interpretation_response
          ),
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

  const examples = EXAMPLE_QUESTIONS

  return (
    <div className={`flex min-h-0 flex-col bg-[linear-gradient(180deg,_rgba(248,250,252,0.92),_rgba(255,255,255,0.98))] ${fullScreen ? 'h-full' : 'min-h-[620px]'}`}>
      {/* Header */}
      <div className="shrink-0 border-b border-slate-200 bg-[radial-gradient(circle_at_top_left,_rgba(20,184,166,0.16),_transparent_24%),linear-gradient(135deg,_#0f172a,_#164e63)] p-5 text-white">
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
                Grounded groundwater analysis with USGS data, citations, and chart context
              </p>
            </div>
          </div>

          {/* Showcase keeps the user on the grounded interpretation surface. */}
          <div className="flex overflow-hidden rounded-xl bg-white/10 text-sm ring-1 ring-white/10">
            <div className="flex items-center gap-1 bg-white/20 px-3 py-1.5 font-semibold">
              <MessageCircle className="w-3.5 h-3.5" /> {SHOWCASE_MODE ? 'Grounded Chat' : 'Chat'}
            </div>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
          {SHOWCASE_MODE ? (
            <span className="rounded-full bg-white/10 px-3 py-1.5 text-teal-50/85">
              Deterministic groundwater answers first, with chart interpretation available when needed
            </span>
          ) : (
            <span className="rounded-full bg-white/10 px-3 py-1.5 text-teal-50/85">
              Fast grounded answers for sponsor-ready groundwater prompts
            </span>
          )}
          {REQUEST_LLM_INTERPRETATION && (
            <span className="rounded-full bg-teal-400/15 px-3 py-1.5 text-teal-100">
              Structured LLM synthesis requested; deterministic fallback stays in place if the model is unavailable
            </span>
          )}
          {agentStatus?.research_available === false && (
            <span className="rounded-full bg-white/10 px-3 py-1.5 text-teal-50/75">
              Deep research remains backend-only future work
            </span>
          )}
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
      <div className={`${fullScreen ? 'min-h-0 flex-1 overflow-y-auto overscroll-contain' : ''} bg-[linear-gradient(180deg,_rgba(248,250,252,0.65),_rgba(241,245,249,0.85))] p-4`}>
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
              className={`${fullScreen ? 'max-w-[min(980px,86%)]' : 'max-w-[80%]'} rounded-lg p-3 ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : msg.error
                  ? 'bg-red-50 border border-red-200 text-red-800'
                  : msg.isProgress
                  ? 'bg-amber-50 border border-amber-200 text-amber-800'
                  : msg.answerType === 'insufficient_evidence'
                  ? 'bg-slate-50 border border-slate-300 text-slate-700'
                  : 'bg-white border border-slate-200 text-slate-800'
              }`}
            >
              {msg.role === 'assistant' && msg.groundingStatus && (
                <div className="mb-2 flex flex-wrap items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide">
                  <span
                    className={`rounded-full px-2 py-0.5 ${
                      msg.groundingStatus === 'grounded'
                        ? 'bg-emerald-100 text-emerald-800'
                        : msg.groundingStatus === 'partial'
                        ? 'bg-amber-100 text-amber-800'
                        : msg.groundingStatus === 'refused'
                        ? 'bg-slate-200 text-slate-700'
                        : 'bg-slate-100 text-slate-600'
                    }`}
                  >
                    {msg.groundingStatus}
                  </span>
                  {!SHOWCASE_MODE && msg.routeMode && (
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">{msg.routeMode}</span>
                  )}
                </div>
              )}
              <div className="text-sm leading-relaxed">
                <ReactMarkdown components={markdownComponents}>{msg.content}</ReactMarkdown>
              </div>
              {msg.groundedAnswer && Array.isArray(msg.groundedAnswer.grounded_findings) && msg.groundedAnswer.grounded_findings.length > 0 && (
                <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-slate-600">Grounded findings</div>
                  <ul className="mt-2 list-disc space-y-1 pl-4 text-xs leading-5 text-slate-700">
                    {msg.groundedAnswer.grounded_findings.slice(0, 4).map((finding, i) => (
                      <li key={i}>{finding}</li>
                    ))}
                  </ul>
                </div>
              )}
              {msg.groundedAnswer && Array.isArray(msg.groundedAnswer.limits) && msg.groundedAnswer.limits.length > 0 && (
                <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-amber-800">Limits</div>
                  <ul className="mt-2 list-disc space-y-1 pl-4 text-xs leading-5 text-slate-700">
                    {msg.groundedAnswer.limits.slice(0, 2).map((limit, i) => (
                      <li key={i}>{limit}</li>
                    ))}
                  </ul>
                </div>
              )}
              {msg.groundedAnswer?.next_best_question && !msg.interpretationResponse && msg.answerType !== 'insufficient_evidence' && (
                <button
                  type="button"
                  onClick={() => sendMessage(msg.groundedAnswer.next_best_question)}
                  className="mt-3 inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-800 hover:bg-emerald-100"
                >
                  Ask next: {msg.groundedAnswer.next_best_question}
                </button>
              )}
              {msg.groundedAnswer?.next_best_question && msg.answerType === 'insufficient_evidence' && (
                <button
                  type="button"
                  onClick={() => sendMessage(msg.groundedAnswer.next_best_question)}
                  className="mt-3 inline-flex items-center rounded-full border border-slate-300 bg-white px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
                >
                  Try: {msg.groundedAnswer.next_best_question}
                </button>
              )}

              {msg.rawContent && (
                <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <summary className="cursor-pointer text-xs font-medium text-slate-600">
                    Evidence report
                  </summary>
                  <div className="mt-2 text-xs leading-relaxed text-slate-700">
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
                    Interpretation
                  </div>
                  {msg.interpretationResponse.interpretation
                    && msg.interpretationResponse.interpretation !== msg.content && (
                      <p className="mt-2 text-sm leading-relaxed text-slate-800">
                        {msg.interpretationResponse.interpretation}
                      </p>
                    )}

                  {resolveNextGoal(msg) && (
                    <div className="mt-3 rounded-md border border-emerald-200 bg-white/80 p-2">
                      <p className="text-[11px] font-medium text-emerald-800">Next goal</p>
                      <p className="mt-1 text-xs leading-5 text-slate-700">{resolveNextGoal(msg)}</p>
                    </div>
                  )}

                  {(() => {
                    const followUpGroups = buildGroupedFollowUps(msg)
                    if (followUpGroups.length === 0) return null
                    return (
                      <div className="mt-2 border-t border-emerald-200 pt-2">
                        <p className="text-[11px] font-medium text-emerald-800">Ask Next</p>
                        <div className="mt-2 space-y-2">
                          {followUpGroups.map(group => (
                            <div key={group.label}>
                              <p className="text-[10px] font-medium uppercase tracking-wide text-emerald-700">{group.label}</p>
                              <div className="mt-1 flex flex-wrap gap-1.5">
                                {group.items.map((item, i) => (
                                  <button
                                    key={`${group.label}-${i}`}
                                    type="button"
                                    onClick={() => {
                                      logLearnerEvent({
                                        event_type: 'ask_next_clicked',
                                        message_id: msg.id,
                                        question: msg.questionAsked || '',
                                        chart_id: msg.chartContextRef?.chart_id || msg.chart?.title || '',
                                        details: { group: group.label, follow_up: item },
                                      })
                                      sendMessage(item, {
                                        chartContext: msg.chartContextRef || chartContextFromMessage(msg),
                                        forceInterpretation: true,
                                      })
                                    }}
                                    className="rounded-md border border-emerald-200 bg-white px-2 py-1 text-left text-[11px] text-emerald-900 hover:bg-emerald-100"
                                  >
                                    {item}
                                  </button>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )
                  })()}

                  {msg.interpretationResponse.grounding_status && (
                    <div className="mt-2 text-[10px] text-slate-500">
                      USGS data: {msg.interpretationResponse.grounding_status.uses_usgs_data ? 'yes' : 'no'} · Chart context: {msg.interpretationResponse.grounding_status.uses_chart_context ? 'yes' : 'no'} · LLM: {llmGroundingLabel(msg.interpretationResponse.grounding_status)}
                    </div>
                  )}
                </div>
              )}

              {msg.role === 'assistant' && (() => {
                const depth = buildAnalyticalDepth(msg)
                if (!depth) return null
                return (
                  <details
                    className="mt-3 rounded-lg border border-slate-200 bg-white p-3"
                    onToggle={event => {
                      if (event.currentTarget.open) {
                        logLearnerEvent({
                          event_type: 'analytical_depth_expanded',
                          message_id: msg.id,
                          question: msg.questionAsked || '',
                          chart_id: msg.chartContextRef?.chart_id || msg.chart?.title || '',
                          details: { cohort_risk: depth.cohortRisk || null },
                        })
                      }
                    }}
                  >
                    <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                          See the evidence behind this explanation
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          {(depth.reasoningSource === 'grounded_llm' || depth.reasoningSource === 'grounded_claude')
                            ? 'Grounded reasoning, deterministic signals, and support checks behind this answer.'
                            : depth.reasoningSource === 'llm_polish'
                              ? 'Deterministic signals with an LLM-polished explanation and support checks.'
                              : 'Deterministic signals, limits, and support checks behind this answer.'}
                        </p>
                      </div>
                      {depth.cohortRisk && (
                        <span className={`rounded-md px-2 py-1 text-[11px] font-medium ${
                          depth.cohortRisk === 'high' ? 'bg-red-100 text-red-700'
                          : depth.cohortRisk === 'moderate' ? 'bg-amber-100 text-amber-700'
                          : 'bg-green-100 text-green-700'
                        }`}>
                          {depth.cohortRisk} risk
                        </span>
                      )}
                    </summary>

                    {depth.numericClaims.length > 0 && (
                      <div className="mt-3 grid gap-2 md:grid-cols-3">
                        {depth.numericClaims.slice(0, 6).map((claim, i) => (
                          <div key={`${claim.site}-${claim.source}-${i}`} className="rounded-md border border-slate-200 bg-slate-50 p-2">
                            <p className="truncate text-[11px] font-medium text-slate-600">{claim.site}</p>
                            <p className="mt-1 text-sm font-semibold text-slate-900">
                              {formatSigned(claim.value)} {claim.unit}
                            </p>
                            <p className="mt-0.5 truncate text-[10px] text-slate-400">{numericSourceLabel(claim.source)}</p>
                          </div>
                        ))}
                      </div>
                    )}

                    {depth.reasoningTrace.length > 0 && (
                      <div className="mt-3 rounded-md border border-sky-200 bg-sky-50 p-3">
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-[11px] font-medium text-sky-800">How the AI reached this answer</p>
                          <span className="rounded-md bg-white px-2 py-1 text-[10px] font-medium text-sky-900">
                            {(depth.reasoningSource === 'grounded_llm' || depth.reasoningSource === 'grounded_claude')
                              ? 'Grounded AI reasoning'
                              : 'Reasoning trace'}
                          </span>
                        </div>
                        <div className="mt-2 space-y-2">
                          {depth.reasoningTrace.slice(0, 6).map((step, i) => (
                            <div key={`${step.step_label || 'step'}-${i}`} className="rounded-md bg-white/80 p-2 text-xs">
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <p className="font-medium text-slate-800">{step.step_label || `Step ${i + 1}`}</p>
                                <span className={`rounded-md px-2 py-0.5 text-[10px] font-medium ${
                                  step.confidence === 'low' ? 'bg-amber-100 text-amber-800'
                                  : step.confidence === 'medium' ? 'bg-sky-100 text-sky-800'
                                  : 'bg-emerald-100 text-emerald-800'
                                }`}>
                                  {step.confidence || 'grounded'}
                                </span>
                              </div>
                              {step.observation && (
                                <p className="mt-1 leading-5 text-slate-700">{step.observation}</p>
                              )}
                              {step.inference && (
                                <p className="mt-1 leading-5 text-slate-600 italic">{step.inference}</p>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {depth.langgraphTrace.length > 0 && (
                      <details className="mt-3 rounded-md border border-violet-200 bg-violet-50 p-3">
                        <summary className="cursor-pointer text-[11px] font-medium text-violet-800">
                          LangGraph execution trace ({depth.langgraphTrace.length} step{depth.langgraphTrace.length === 1 ? '' : 's'})
                        </summary>
                        <ol className="mt-2 space-y-1.5 text-xs text-slate-700">
                          {depth.langgraphTrace.map((node, i) => {
                            const { node: nodeName, ...rest } = node || {}
                            const detail = Object.entries(rest)
                              .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
                              .join(' · ')
                            return (
                              <li key={`lg-${i}`} className="rounded-md bg-white/80 px-2 py-1.5">
                                <span className="font-medium text-violet-900">{nodeName || `node ${i + 1}`}</span>
                                {detail && <span className="ml-2 text-[11px] text-slate-600">{detail}</span>}
                              </li>
                            )
                          })}
                        </ol>
                      </details>
                    )}

                    {depth.aquiferSummaries.length > 0 && (
                      <div className="mt-3">
                        <p className="text-[11px] font-medium text-slate-500">Aquifer comparison</p>
                        <div className="mt-1 grid gap-1.5 md:grid-cols-2">
                          {depth.aquiferSummaries.slice(0, 4).map((item, i) => (
                            <div key={`${item.zone}-${i}`} className="rounded-md bg-slate-50 px-2 py-1.5 text-xs text-slate-600">
                              <span className="font-medium text-slate-800">{item.zone || item.aquifer}</span>
                              <span> · {formatSigned(item.mean_annual_change)} ft/yr</span>
                              <span> · {item.n_falling || 0} falling / {item.n_rising || 0} rising</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {depth.supplyUnits.length > 0 && (
                      <div className="mt-3">
                        <p className="text-[11px] font-medium text-slate-500">Supply proxy mapping</p>
                        <div className="mt-1 flex flex-wrap gap-1.5">
                          {depth.supplyUnits.slice(0, 4).map((unit, i) => (
                            <span key={`${unit.zone}-${i}`} className="rounded-md bg-teal-50 px-2 py-1 text-xs text-teal-800">
                              {unit.zone}: {(unit.proxy_wells || []).length} proxy well{(unit.proxy_wells || []).length === 1 ? '' : 's'}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {depth.comparisonGroups?.shallow_unconfined && depth.comparisonGroups?.deep_confined && (
                      <div className="mt-3 rounded-md border border-teal-100 bg-teal-50 p-2">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div>
                            <p className="text-[11px] font-medium text-teal-800">Shallow vs deep comparison</p>
                            <p className="mt-1 text-xs leading-5 text-slate-700">
                              {depth.comparisonGroups.shallow_unconfined.count || 0} shallow/unconfined well{depth.comparisonGroups.shallow_unconfined.count === 1 ? '' : 's'} average {formatSigned(depth.comparisonGroups.shallow_unconfined.mean_annual_change_ft_yr)} ft/yr; {depth.comparisonGroups.deep_confined.count || 0} deep/confined well{depth.comparisonGroups.deep_confined.count === 1 ? '' : 's'} average {formatSigned(depth.comparisonGroups.deep_confined.mean_annual_change_ft_yr)} ft/yr.
                            </p>
                          </div>
                          {Number.isFinite(Number(depth.largestGap?.gap_ft_yr)) && (
                            <span className="rounded-md bg-white px-2 py-1 text-[11px] font-medium text-teal-900">
                              largest gap {Number(depth.largestGap.gap_ft_yr).toFixed(3)} ft/yr
                            </span>
                          )}
                        </div>
                        {(Number.isFinite(Number(depth.comparisonGroups.shallow_unconfined.mean_seasonal_amplitude_ft)) || Number.isFinite(Number(depth.comparisonGroups.deep_confined.mean_seasonal_amplitude_ft))) && (
                          <p className="mt-1 text-[11px] leading-5 text-slate-600">
                            Seasonal amplitude: shallow {formatSigned(depth.comparisonGroups.shallow_unconfined.mean_seasonal_amplitude_ft, 1)} ft; deep {formatSigned(depth.comparisonGroups.deep_confined.mean_seasonal_amplitude_ft, 1)} ft.
                          </p>
                        )}
                        {depth.largestGap?.site_a?.name && depth.largestGap?.site_b?.name && (
                          <p className="mt-1 text-[11px] leading-5 text-slate-600">
                            The widest well-level separation is {depth.largestGap.site_a.name} versus {depth.largestGap.site_b.name}.
                          </p>
                        )}
                      </div>
                    )}

                    {depth.meaningBrief && (
                      <div className="mt-3 rounded-md border border-emerald-100 bg-emerald-50 p-3">
                        <p className="text-[11px] font-medium text-emerald-800">What this means</p>
                        <p className="mt-1 text-sm font-semibold leading-5 text-slate-900">
                          {depth.meaningBrief.headline}
                        </p>
                        <p className="mt-1 text-xs leading-5 text-slate-700">
                          {depth.meaningBrief.plain_language}
                        </p>
                        <div className="mt-2 grid gap-2 md:grid-cols-3">
                          <div>
                            <p className="text-[10px] font-medium uppercase tracking-wide text-emerald-700">Why it matters</p>
                            <p className="mt-0.5 text-[11px] leading-5 text-slate-700">{depth.meaningBrief.why_it_matters}</p>
                          </div>
                          <div>
                            <p className="text-[10px] font-medium uppercase tracking-wide text-emerald-700">How to read it</p>
                            <p className="mt-0.5 text-[11px] leading-5 text-slate-700">{depth.meaningBrief.how_to_read}</p>
                          </div>
                          <div>
                            <p className="text-[10px] font-medium uppercase tracking-wide text-emerald-700">Next check</p>
                            <p className="mt-0.5 text-[11px] leading-5 text-slate-700">{depth.meaningBrief.next_best_check}</p>
                          </div>
                        </div>
                      </div>
                    )}

                    {(depth.interpretiveFindings.length > 0 || depth.possibleDrivers.length > 0 || depth.evidenceNeeded.length > 0) && (
                      <div className="mt-3 grid gap-3 md:grid-cols-3">
                        <div className="rounded-md bg-emerald-50 p-2">
                          <p className="text-[11px] font-medium text-emerald-800">Hydro meaning</p>
                          <p className="mt-1 text-xs leading-5 text-slate-700">
                            {depth.interpretiveFindings.find(item => item.label === 'Hydrogeologic meaning')?.text
                              || depth.managementImplications[0]
                              || 'This is an evidence-bound screening interpretation of the observed monitoring pattern.'}
                          </p>
                        </div>
                        <div className="rounded-md bg-sky-50 p-2">
                          <p className="text-[11px] font-medium text-sky-800">Possible explanations</p>
                          <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-slate-700">
                            {depth.possibleDrivers.slice(0, 3).map((item, i) => (
                              <li key={`driver-${i}`}>{item}</li>
                            ))}
                            {depth.possibleDrivers.length === 0 && <li>Use outside data to test the observed signal.</li>}
                          </ul>
                        </div>
                        <div className="rounded-md bg-amber-50 p-2">
                          <p className="text-[11px] font-medium text-amber-800">What would confirm it</p>
                          <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-slate-700">
                            {depth.evidenceNeeded.slice(0, 3).map((item, i) => (
                              <li key={`evidence-${i}`}>{item}</li>
                            ))}
                            {depth.evidenceNeeded.length === 0 && <li>Additional covariates and nearby wells.</li>}
                          </ul>
                        </div>
                      </div>
                    )}

                    {depth.confidenceNotes.length > 0 && (
                      <div className="mt-3 rounded-md bg-slate-50 p-2">
                        <p className="text-[11px] font-medium text-slate-500">Confidence note</p>
                        <p className="mt-1 text-xs leading-5 text-slate-600">{depth.confidenceNotes[0]}</p>
                      </div>
                    )}

                    {depth.groundwaterConcepts.length > 0 && (
                      <div className="mt-3">
                        <p className="text-[11px] font-medium text-slate-500">Groundwater concepts</p>
                        <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-slate-600">
                          {depth.groundwaterConcepts.slice(0, 3).map((concept, i) => (
                            <li key={`${concept.id || 'concept'}-${i}`}>
                              {String(concept.summary || '').split('Caveat:')[0].trim()}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {(depth.observations.length > 0 || depth.limits.length > 0 || depth.guardrailFlags.length > 0) && (
                      <div className="mt-3 grid gap-3 md:grid-cols-2">
                        {depth.observations.length > 0 && (
                          <div>
                            <p className="text-[11px] font-medium text-slate-500">Key observations</p>
                            <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-slate-600">
                              {depth.observations.slice(0, 3).map((item, i) => (
                                <li key={i}>{item}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        <div>
                          <p className="text-[11px] font-medium text-slate-500">Limits and guardrails</p>
                          <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-slate-600">
                            {depth.limits.slice(0, 3).map((item, i) => (
                              <li key={`limit-${i}`}>{item}</li>
                            ))}
                            {depth.guardrailFlags.slice(0, 2).map((item, i) => (
                              <li key={`guardrail-${i}`}>{item}</li>
                            ))}
                            {depth.limits.length === 0 && depth.guardrailFlags.length === 0 && (
                              <li>All displayed measurements come from deterministic evidence fields.</li>
                            )}
                          </ul>
                        </div>
                      </div>
                    )}

                    {depth.grounding && (
                      <div className="mt-3 border-t border-slate-200 pt-2 text-[10px] text-slate-500">
                        Chart context: {depth.grounding.uses_chart_context ? 'yes' : 'no'} · USGS data: {depth.grounding.uses_usgs_data ? 'yes' : 'no'} · Invented measurements: {depth.grounding.invented_measurements_allowed ? 'allowed' : 'blocked'}
                      </div>
                    )}
                  </details>
                )
              })()}

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

              {Array.isArray(msg.interpretationDetails?.per_site_quant) && msg.interpretationDetails.per_site_quant.length > 0 && (
                <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <summary className="cursor-pointer text-xs font-medium text-slate-800">
                    Quantitative evidence ({msg.interpretationDetails.per_site_quant.length} site{msg.interpretationDetails.per_site_quant.length === 1 ? '' : 's'})
                  </summary>
                  <div className="mt-2 overflow-x-auto">
                    <table className="w-full text-xs text-slate-700">
                      <thead className="text-[10px] uppercase text-slate-500">
                        <tr>
                          <th className="text-left py-1 pr-3">Site</th>
                          <th className="text-right py-1 pr-3">Rate (ft/yr)</th>
                          <th className="text-right py-1 pr-3">95% CI</th>
                          <th className="text-right py-1 pr-3">MK p</th>
                          <th className="text-right py-1 pr-3">Sen slope</th>
                          <th className="text-left py-1">Record</th>
                        </tr>
                      </thead>
                      <tbody>
                        {msg.interpretationDetails.per_site_quant.map((row, i) => {
                          const ciLow = row.rate_ci95_low
                          const ciHigh = row.rate_ci95_high
                          const ci = (ciLow != null && ciHigh != null)
                            ? `[${ciLow.toFixed(3)}, ${ciHigh.toFixed(3)}]`
                            : '—'
                          const fmt = (v, d = 3) => (v == null ? '—' : Number(v).toFixed(d))
                          const window = (row.record_start && row.record_end)
                            ? `${row.record_start.slice(0, 4)}–${row.record_end.slice(0, 4)}`
                            : (row.record_years ? `${row.record_years.toFixed(1)} yr` : '—')
                          return (
                            <tr key={`${row.site_id || row.site}-${i}`} className="border-t border-slate-200">
                              <td className="py-1 pr-3 font-medium">{row.site}</td>
                              <td className="py-1 pr-3 text-right tabular-nums">{fmt(row.rate_ft_yr)}</td>
                              <td className="py-1 pr-3 text-right tabular-nums">{ci}</td>
                              <td className="py-1 pr-3 text-right tabular-nums">{fmt(row.mk_pvalue, 3)}</td>
                              <td className="py-1 pr-3 text-right tabular-nums">{fmt(row.sens_slope_ft_yr)}</td>
                              <td className="py-1 text-slate-500">{window}</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </details>
              )}

              {Array.isArray(msg.interpretationDetails?.driver_hypotheses) && msg.interpretationDetails.driver_hypotheses.length > 0 && (
                <details className="mt-3 rounded-lg border border-indigo-200 bg-indigo-50 p-3">
                  <summary className="cursor-pointer text-xs font-medium text-indigo-800">
                    Driver hypotheses ({msg.interpretationDetails.driver_hypotheses.length})
                  </summary>
                  <div className="mt-2 space-y-2">
                    {msg.interpretationDetails.driver_hypotheses.slice(0, 3).map((h, i) => {
                      const confColor = h.confidence === 'high'
                        ? 'bg-green-100 text-green-700'
                        : h.confidence === 'medium'
                          ? 'bg-amber-100 text-amber-700'
                          : 'bg-slate-100 text-slate-600'
                      return (
                        <div key={i} className="rounded-md bg-white p-2 text-xs">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700 font-medium text-[10px]">
                              {h.mechanism || 'other'}
                            </span>
                            {h.confidence && (
                              <span className={`px-1.5 py-0.5 rounded font-medium text-[10px] ${confColor}`}>
                                {h.confidence}
                              </span>
                            )}
                          </div>
                          <p className="text-slate-800">{h.claim}</p>
                          {h.falsification_test && (
                            <p className="mt-1 text-slate-500 italic">
                              Falsifier: {h.falsification_test}
                            </p>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </details>
              )}

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

              {onOpenWorkbench && Array.isArray(msg.wells) && msg.wells.length > 0 && (
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
        <div ref={messagesEndRef} />
      </div>

      {/* Example Questions */}
      <div className="shrink-0 border-t border-slate-200 bg-white/90 p-4">
        <p className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">
          Try asking:
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
      <div className={`${fullScreen ? 'shrink-0' : 'sticky bottom-0 z-20'} border-t border-slate-200 bg-white/95 p-4 backdrop-blur`}>
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
            placeholder="Ask about groundwater levels, aquifers, well depth, trends, or supply risk..."
            className="flex-1 rounded-2xl border border-slate-300 bg-slate-50 px-4 py-2.5 text-sm shadow-inner focus:border-transparent focus:outline-none focus:ring-2 focus:ring-teal-500"
            disabled={loading}
          />
          <button
            onClick={() => sendMessage()}
            disabled={loading || !input.trim()}
            className="flex items-center gap-2 rounded-2xl bg-slate-900 px-4 py-2 text-white transition-colors hover:bg-teal-700 disabled:bg-slate-300"
          >
            <Send className="w-4 h-4" />
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
