import { useState, useEffect, useRef } from 'react'
import { Send, Bot, User, AlertCircle, Sparkles, Search, MessageCircle } from 'lucide-react'
import { sendChatMessage, sendResearchQuery, fetchChatStatus } from '../api/client'

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
        // Deep Research mode
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: '🔍 Starting deep research — this may take a moment…',
          isProgress: true,
        }])

        const data = await sendResearchQuery(text)

        // Remove progress indicator, add real response
        setMessages(prev => {
          const filtered = prev.filter(m => !m.isProgress)
          return [...filtered, {
            role: 'assistant',
            content: data.report || data.response || 'Research complete — no report generated.',
            context: `Depth reached: ${data.depth_reached} | Elapsed: ${Math.round(data.elapsed_seconds)}s`,
            sources: data.sources || [],
            insights: data.insights || [],
            mode: data.mode,
          }]
        })
      } else {
        // Quick chat mode
        const data = await sendChatMessage(text)

        setMessages(prev => [...prev, {
          role: 'assistant',
          content: data.response,
          context: data.context,
          sources: data.sources || [],
          mode: data.mode,
          status: data.status,
        }])
      }
    } catch (error) {
      console.error('Chat error:', error)
      setMessages(prev => {
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

              {msg.mode && (
                <div className="mt-2 flex items-center gap-1 text-xs text-slate-400">
                  {msg.mode === 'agent' && '🤖 Agent'}
                  {msg.mode === 'deep_research' && '🔬 Deep Research'}
                  {msg.mode === 'fallback' && '📋 Rule-based'}
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
