import { useState } from 'react'
import { Send, Bot, User, AlertCircle, Sparkles } from 'lucide-react'

const EXAMPLE_QUESTIONS = [
  "What water table depth is best for citrus trees?",
  "How does the dry season affect groundwater levels?",
  "Is the Biscayne Aquifer at risk from saltwater intrusion?",
  "What should farmers know about irrigation planning?",
  "Which aquifer is used in Lee County?",
]

export default function ChatView({ selectedSite }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: "👋 Welcome to GroundwaterGPT! I can help answer questions about groundwater, irrigation, crops, and aquifers in Florida. This feature is under construction - full AI integration coming soon!",
      sources: [],
    }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)

  const sendMessage = async (text = input) => {
    if (!text.trim()) return

    // Add user message
    const userMessage = { role: 'user', content: text }
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setLoading(true)

    try {
      const response = await fetch('http://localhost:8000/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      })

      if (!response.ok) throw new Error('Chat request failed')

      const data = await response.json()

      // Add assistant response
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.response,
        context: data.context,
        sources: data.sources || [],
        status: data.status,
      }])
    } catch (error) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: "Sorry, I couldn't process that request. Please try again.",
        error: true,
      }])
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

  return (
    <div className="flex flex-col h-[600px]">
      {/* Header */}
      <div className="bg-gradient-to-r from-blue-600 to-cyan-600 text-white p-4 rounded-t-lg">
        <div className="flex items-center gap-3">
          <div className="bg-white/20 p-2 rounded-lg">
            <Bot className="w-6 h-6" />
          </div>
          <div>
            <h3 className="font-bold text-lg">GroundwaterGPT Assistant</h3>
            <p className="text-blue-100 text-sm flex items-center gap-1">
              <Sparkles className="w-3 h-3" />
              Beta - AI features under construction
            </p>
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
                  : 'bg-white border border-slate-200 text-slate-800'
              }`}
            >
              <p className="text-sm leading-relaxed">{msg.content}</p>

              {msg.context && (
                <p className="text-xs mt-2 opacity-70 border-t border-slate-200 pt-2">
                  📍 {msg.context}
                </p>
              )}

              {msg.sources && msg.sources.length > 0 && (
                <div className="mt-2 pt-2 border-t border-slate-200">
                  <p className="text-xs text-slate-500">Sources:</p>
                  {msg.sources.map((src, i) => (
                    <span key={i} className="text-xs text-blue-600 mr-2">• {src}</span>
                  ))}
                </div>
              )}

              {msg.status === 'beta' && (
                <div className="mt-2 flex items-center gap-1 text-xs text-amber-600">
                  <AlertCircle className="w-3 h-3" />
                  Beta response - verify with official sources
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

        {loading && (
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
      <div className="bg-white border-t border-slate-200 p-3">
        <p className="text-xs text-slate-500 mb-2">Try asking:</p>
        <div className="flex flex-wrap gap-2">
          {EXAMPLE_QUESTIONS.slice(0, 3).map((q, i) => (
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
            placeholder="Ask about groundwater, irrigation, crops..."
            className="flex-1 border border-slate-300 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            disabled={loading}
          />
          <button
            onClick={() => sendMessage()}
            disabled={loading || !input.trim()}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-slate-300 text-white px-4 py-2 rounded-lg transition-colors flex items-center gap-2"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
