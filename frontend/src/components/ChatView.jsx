import { useState, useEffect, useRef } from 'react'
import { Send, Bot, User, AlertCircle, Sparkles, Search, MessageCircle } from 'lucide-react'
import { sendChatMessage, sendResearchQueryStreaming, fetchChatStatus } from '../api/client'
import AgentChart from './AgentChart'

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

const EXAMPLE_QUESTIONS = [
  "What water table depth is best for citrus trees?",
  "How does the dry season affect groundwater levels?",
  "Is the Biscayne Aquifer at risk from saltwater intrusion?",
  "What should farmers know about irrigation planning?",
  "Which aquifer is used in Lee County?",
]

const RESEARCH_EXAMPLES = [
  "What are the long-term trends for Biscayne Aquifer sites?",
  "Compare water levels in Miami-Dade vs Collier County over the last 5 years",
  "What does the literature say about saltwater intrusion in Southeast Florida?",
]

export default function ChatView({ selectedSite }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: "👋 Welcome to GroundwaterGPT! I can help answer questions about groundwater, irrigation, crops, and aquifers in Florida. Switch to Deep Research mode for multi-step investigations with source citations.",
      sources: [],
    }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [mode, setMode] = useState('chat') // 'chat' | 'research'
  const [agentStatus, setAgentStatus] = useState(null)
  const messagesEndRef = useRef(null)

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Check agent status on mount
  useEffect(() => {
    fetchChatStatus()
      .then(setAgentStatus)
      .catch(() => setAgentStatus(null))
  }, [])

  const sendMessage = async (text = input) => {
    if (!text.trim()) return

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
          content: '🔍 Starting deep research…',
          isProgress: true,
          progressId: PROGRESS_ID,
          progressValue: 0,
        }])

        // onProgress updates the existing progress bubble in-place rather
        // than appending new messages, keeping the thread tidy.
        const handleProgress = (message, progress) => {
          setMessages(prev => prev.map(m =>
            m.progressId === PROGRESS_ID
              ? { ...m, content: `🔍 ${message}`, progressValue: progress }
              : m
          ))
        }

        const data = await sendResearchQueryStreaming(text, { onProgress: handleProgress })
        const { text: reportText, chart } = extractChart(
          data.report || data.response || 'Research complete — no report generated.'
        )

        // Swap out the progress bubble for the finished report.
        setMessages(prev => {
          const filtered = prev.filter(m => m.progressId !== PROGRESS_ID)
          const elapsedSeconds = Number.isFinite(data.elapsed_seconds)
            ? Math.round(data.elapsed_seconds)
            : 0
          return [...filtered, {
            role: 'assistant',
            content: reportText,
            chart,
            context: `Depth reached: ${data.depth_reached ?? 0} | Elapsed: ${elapsedSeconds}s`,
            sources: data.sources || [],
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
            mode: data.mode,
          }]
        })
      } else {
        // Quick chat mode
        const data = await sendChatMessage(text)
        const { text: replyText, chart } = extractChart(data.response)

        setMessages(prev => [...prev, {
          role: 'assistant',
          content: replyText,
          chart,
          context: data.context,
          sources: data.sources || [],
          wells: data.wells || [],
          aquiferInfo: data.aquifer_info || null,
          divergentPairs: data.divergent_pairs || [],
          cohortRisk: data.cohort_risk_level || null,
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
    <div className="flex flex-col h-[600px]">
      {/* Header */}
      <div className="bg-gradient-to-r from-blue-600 to-cyan-600 text-white p-4 rounded-t-lg">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="bg-white/20 p-2 rounded-lg">
              <Bot className="w-6 h-6" />
            </div>
            <div>
              <h3 className="font-bold text-lg">GroundwaterGPT Assistant</h3>
              <p className="text-blue-100 text-sm flex items-center gap-1">
                <Sparkles className="w-3 h-3" />
                {agentStatus?.agent_available
                  ? 'LLM-powered agent active'
                  : 'Rule-based mode (LLM agent unavailable)'}
              </p>
            </div>
          </div>

          {/* Mode Toggle */}
          <div className="flex bg-white/20 rounded-lg overflow-hidden text-sm">
            <button
              onClick={() => setMode('chat')}
              className={`flex items-center gap-1 px-3 py-1.5 transition-colors ${
                mode === 'chat' ? 'bg-white/30 font-semibold' : 'hover:bg-white/10'
              }`}
            >
              <MessageCircle className="w-3.5 h-3.5" /> Chat
            </button>
            <button
              onClick={() => setMode('research')}
              className={`flex items-center gap-1 px-3 py-1.5 transition-colors ${
                mode === 'research' ? 'bg-white/30 font-semibold' : 'hover:bg-white/10'
              }`}
            >
              <Search className="w-3.5 h-3.5" /> Research
            </button>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-slate-50">
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
              <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</p>

              {/* Progress bar — only shown on the live research status bubble */}
              {msg.isProgress && msg.progressValue > 0 && (
                <div className="mt-2 h-1.5 bg-amber-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-amber-500 rounded-full transition-all duration-500"
                    style={{ width: `${Math.round(msg.progressValue * 100)}%` }}
                  />
                </div>
              )}

              {/* Inline chart from agent visualization tools */}
              {msg.chart && (
                <div className="mt-3 -mx-1">
                  <AgentChart chartData={msg.chart} />
                </div>
              )}

              {msg.context && (
                <p className="text-xs mt-2 opacity-70 border-t border-slate-200 pt-2">
                  📍 {msg.context}
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
                    ✅ {msg.claimVerdictSummary.supported_claims} supported
                  </span>
                  {/* Contradicted count — red, only shown when >0 */}
                  {msg.claimVerdictSummary.contradicted_claims > 0 && (
                    <span className="inline-flex items-center gap-1 bg-red-50 text-red-700 border border-red-200 px-2 py-0.5 rounded-full">
                      ⚠ {msg.claimVerdictSummary.contradicted_claims} contradicted
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
                      ⚠ {Math.round(msg.claimVerdictSummary.contradicted_claim_rate * 100)}% of claims conflict — see report below
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
                        verdict === 'supported' ? '✅'
                        : verdict === 'contradicted' ? '⚠'
                        : '—'

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

              {msg.wells && msg.wells.length > 0 && (
                <details className="mt-2 pt-2 border-t border-slate-200">
                  <summary className="text-xs text-slate-500 cursor-pointer">
                    Well details — {msg.wells.length} monitoring site{msg.wells.length > 1 ? 's' : ''}
                    {msg.aquiferInfo && (
                      <span className="ml-2 text-slate-400">
                        | {msg.aquiferInfo.name}
                        {msg.aquiferInfo.monitored_wells != null && ` (${msg.aquiferInfo.monitored_wells} wells monitored)`}
                      </span>
                    )}
                  </summary>
                  <ul className="mt-2 space-y-2">
                    {msg.wells.map((w) => {
                      const confined = w.confined
                      const badgeColor = confined ? 'bg-blue-100 text-blue-700' : 'bg-green-100 text-green-700'
                      const zoneRange = Array.isArray(w.aquifer_zone_depth_range_ft)
                        ? `${w.aquifer_zone_depth_range_ft[0]}–${w.aquifer_zone_depth_range_ft[1]} ft`
                        : null
                      const marginFt = w.saturation_margin_ft
                      const marginLabel = marginFt != null
                        ? marginFt >= 0
                          ? `${marginFt} ft above zone top`
                          : `${Math.abs(marginFt)} ft below zone top ⚠️`
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
                </details>
              )}

              {msg.divergentPairs && msg.divergentPairs.length > 0 && (
                <details className="mt-2 pt-2 border-t border-slate-200">
                  <summary className="text-xs text-slate-500 cursor-pointer">
                    ⚡ {msg.divergentPairs.length} divergent well pair{msg.divergentPairs.length > 1 ? 's' : ''} detected
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

              {msg.mode && (
                <div className="mt-2 flex items-center gap-1 text-xs text-slate-400">
                  {msg.mode === 'agent' && '🤖 Agent'}
                  {msg.mode === 'deep_research' && '🔬 Deep Research'}
                  {msg.mode === 'fallback' && '📋 Rule-based'}
                  {msg.mode === 'site_fallback' && '📍 Location Analysis'}
                  {msg.mode === 'aquifer_fallback' && '🌊 Aquifer Analysis'}
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
      <div className="bg-white border-t border-slate-200 p-3">
        <p className="text-xs text-slate-500 mb-2">
          {mode === 'research' ? '🔬 Research examples:' : '💬 Try asking:'}
        </p>
        <div className="flex flex-wrap gap-2">
          {examples.slice(0, 3).map((q, i) => (
            <button
              key={i}
              onClick={() => sendMessage(q)}
              className="text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 px-3 py-1.5 rounded-full transition-colors"
            >
              {q}
            </button>
          ))}
        </div>
      </div>

      {/* Input */}
      <div className="bg-white border-t border-slate-200 p-4">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder={
              mode === 'research'
                ? 'Ask a deep-research question…'
                : 'Ask about groundwater, irrigation, crops…'
            }
            className="flex-1 border border-slate-300 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            disabled={loading}
          />
          <button
            onClick={() => sendMessage()}
            disabled={loading || !input.trim()}
            className={`${
              mode === 'research'
                ? 'bg-purple-600 hover:bg-purple-700'
                : 'bg-blue-600 hover:bg-blue-700'
            } disabled:bg-slate-300 text-white px-4 py-2 rounded-lg transition-colors flex items-center gap-2`}
          >
            {mode === 'research' ? <Search className="w-4 h-4" /> : <Send className="w-4 h-4" />}
          </button>
        </div>
      </div>
    </div>
  )
}
