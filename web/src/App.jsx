import { useState, useRef, useEffect, useCallback } from 'react'
import { Send, Square, Globe, Zap, ChevronDown, CheckCircle, Loader, AlertCircle, Bot, User, Maximize2, Minimize2 } from 'lucide-react'
import { useAgentSocket } from './hooks/useAgentSocket'

const SESSION_ID = (() => {
  const key = 'agenticweb.sessionId'
  const existing = window.localStorage.getItem(key)
  if (existing) return existing
  const next = `web-${Math.random().toString(36).slice(2, 8)}`
  window.localStorage.setItem(key, next)
  return next
})()

const PROVIDERS = [
  { id: 'openrouter_qwen', label: 'OR Qwen3 Next', free: true },
  { id: 'openrouter_qwen_coder', label: 'OR Qwen3 Coder', free: true },
  { id: 'openrouter_deepseek', label: 'OR DeepSeek V4', free: true },
  { id: 'openrouter_fast', label: 'OR Nemotron 9B', free: true },
  { id: 'openrouter_nemotron', label: 'OR Nemotron 30B', free: true },
  { id: 'openrouter_glm', label: 'OR GLM 4.5 Air', free: true },
  { id: 'openrouter_llama', label: 'OR Llama 70B', free: true },
  { id: 'openrouter_gptoss', label: 'OR GPT OSS 20B', free: true },
  { id: 'openrouter_gemma', label: 'OR Gemma 31B', free: true },
  { id: 'openrouter_minimax', label: 'OR MiniMax M2.5', free: true },
  { id: 'openrouter_free', label: 'OR Free Router', free: true },
  { id: 'openrouter_auto', label: 'OR Auto Router', free: false },
  { id: 'openrouter_kimi', label: 'OR Kimi K2', free: false },
  { id: 'openrouter', label: 'OR Custom', free: false },
  { id: 'azure_openai', label: 'Azure OpenAI (Microsoft)', free: false },
  { id: 'gemini',   label: 'Gemma 4 31B IT', free: true  },
  { id: 'groq',     label: 'Groq Llama 3.3',   free: true  },
  { id: 'deepseek', label: 'DeepSeek V4 Flash',  free: false },
  { id: 'claude',   label: 'Claude Sonnet',     free: false },
  { id: 'openai',   label: 'GPT-4o Mini',       free: false },
]

const SUGGESTIONS = [
  'Find cheapest flight BLR to GOA this Friday under ₹4000',
  'What is the current gold price in India?',
  'Summarise top 5 HackerNews stories today',
  'Compare iPhone 16 Pro price on Flipkart vs Amazon India',
]

function StatusLine({ event }) {
  const icons = {
    status: <Loader size={12} className="animate-spin text-yellow-400 shrink-0 mt-0.5" />,
    step:   <CheckCircle size={12} className="text-green-400 shrink-0 mt-0.5" />,
    error:  <AlertCircle size={12} className="text-red-400 shrink-0 mt-0.5" />,
  }
  return (
    <div className="flex gap-2 items-start font-mono text-xs text-gray-400 py-0.5">
      {icons[event.type] || null}
      <span>
        {event.type === 'step'
          ? `Step ${event.step} [${event.tool}] → ${event.result?.slice(0, 100)}`
          : event.message || event.result?.slice(0, 120)}
      </span>
    </div>
  )
}

function Message({ msg }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex gap-3 items-start ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* Avatar */}
      <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${isUser ? 'bg-indigo-600' : 'bg-violet-700'}`}>
        {isUser ? <User size={14} /> : <Bot size={14} />}
      </div>

      {/* Bubble */}
      <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${isUser ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-100'}`}>
        {/* Agent log lines */}
        {msg.logs?.length > 0 && (
          <div className="mb-3 space-y-0.5 border-b border-gray-700 pb-3">
            {msg.logs.map((e, i) => <StatusLine key={i} event={e} />)}
          </div>
        )}
        {/* Main content */}
        {msg.content && <p className="whitespace-pre-wrap">{msg.content}</p>}
        {/* Running indicator */}
        {msg.running && !msg.content && (
          <div className="flex gap-1 items-center text-gray-400 text-xs">
            <Loader size={12} className="animate-spin" />
            <span>Working…</span>
          </div>
        )}
      </div>
    </div>
  )
}

export default function App() {
  const [messages, setMessages]     = useState([])
  const [input, setInput]           = useState('')
  const [provider, setProvider]     = useState('openrouter_free')
  const [showProviders, setShowProv]= useState(false)
  const [running, setRunning]       = useState(false)
  const [health, setHealth]         = useState(null)
  const [canvasImg, setCanvasImg]   = useState(null)
  const [canvasOpen, setCanvasOpen] = useState(false)
  const bottomRef                   = useRef(null)
  const inputRef                    = useRef(null)
  const currentMsgId                = useRef(null)

  const updateCurrentAgent = useCallback((patch) => {
    setMessages(prev => {
      const targetId = currentMsgId.current ?? [...prev].reverse().find(m => m.role === 'agent' && m.running)?.id
      if (!targetId) return prev
      return prev.map(m => m.id === targetId ? { ...m, ...patch(m) } : m)
    })
  }, [])

  // Scroll to bottom on new messages
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  // Fetch health on load
  useEffect(() => {
    fetch('/api/health').then(r => r.json()).then(setHealth).catch(() => {})
  }, [])

  const onEvent = useCallback((event) => {
    if (event.type === 'pong') return

    if (event.type === 'canvas') {
      setCanvasImg(event.data)
      setCanvasOpen(true)
      return
    }

    if (event.type === 'done') {
      updateCurrentAgent(m => ({ content: event.result || m.content || 'Done.', running: false, logs: m.logs }))
      setRunning(false)
      currentMsgId.current = null
      return
    }

    if (event.type === 'error') {
      updateCurrentAgent(() => ({ content: `Error: ${event.message}`, running: false }))
      setRunning(false)
      currentMsgId.current = null
      return
    }

    if (event.type === 'cancelled') {
      updateCurrentAgent(() => ({ content: event.message || 'Cancelled by user.', running: false }))
      setRunning(false)
      currentMsgId.current = null
      return
    }

    // status / step — append to current agent message logs
    if (currentMsgId.current) {
      setMessages(prev => prev.map(m =>
        m.id === currentMsgId.current
          ? { ...m, logs: [...(m.logs || []), event] }
          : m
      ))
    }
  }, [updateCurrentAgent])

  const onDisconnect = useCallback(() => {
    if (!currentMsgId.current) return
    updateCurrentAgent(m => ({
      content: m.content || 'Connection lost while the agent was working. Please retry the task.',
      running: false,
    }))
    setRunning(false)
    currentMsgId.current = null
  }, [updateCurrentAgent])

  const { connected, send } = useAgentSocket(SESSION_ID, onEvent, onDisconnect)

  const stop = useCallback(() => {
    if (!running || !connected) return
    send({ type: 'stop' })
  }, [running, connected, send])

  const submit = useCallback(() => {
    const goal = input.trim()
    if (!goal || running || !connected) return

    // Add user message
    setMessages(prev => [...prev, { id: Date.now(), role: 'user', content: goal }])

    // Add placeholder agent message
    const agentId = Date.now() + 1
    currentMsgId.current = agentId
    setMessages(prev => [...prev, { id: agentId, role: 'agent', content: '', logs: [], running: true }])

    setInput('')
    setRunning(true)

    send({ type: 'chat', content: goal, provider })
  }, [input, running, connected, send, provider])

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() }
  }

  const currentProvider = PROVIDERS.find(p => p.id === provider)

  return (
    <div className="flex flex-col h-screen bg-gray-950">

      {/* ── Header ── */}
      <header className="flex items-center gap-3 px-5 py-3 border-b border-gray-800 bg-gray-900">
        <div className="w-8 h-8 rounded-lg bg-violet-600 flex items-center justify-center">
          <Globe size={16} className="text-white" />
        </div>
        <div>
          <h1 className="font-semibold text-sm text-white">AgenticWeb</h1>
          <p className="text-xs text-gray-500">LangGraph · MCP · Autonomous web agent</p>
        </div>

        {/* Connection status */}
        <div className="ml-auto flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-400' : 'bg-red-400'}`} />
          <span className="text-xs text-gray-500">{connected ? 'connected' : 'reconnecting…'}</span>
        </div>

        {/* Canvas toggle */}
        {canvasImg && (
          <button
            onClick={() => setCanvasOpen(v => !v)}
            className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border transition-colors ${canvasOpen ? 'bg-violet-900/40 border-violet-700 text-violet-400' : 'bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-300'}`}
            title={canvasOpen ? 'Close canvas' : 'Open canvas'}
          >
            <Maximize2 size={12} />
            <span className="hidden sm:inline">{canvasOpen ? 'Hide' : 'Canvas'}</span>
          </button>
        )}

        {/* Provider picker */}
        <div className="relative ml-3">
          <button
            onClick={() => setShowProv(v => !v)}
            className="flex items-center gap-2 text-xs bg-gray-800 hover:bg-gray-700 px-3 py-1.5 rounded-lg border border-gray-700 transition-colors"
          >
            <Zap size={12} className="text-violet-400" />
            <span className="text-gray-300">{currentProvider?.label}</span>
            {currentProvider?.free && <span className="text-green-400 text-[10px]">free</span>}
            <ChevronDown size={12} className="text-gray-500" />
          </button>

          {showProviders && (
            <div className="absolute right-0 top-9 w-52 bg-gray-800 border border-gray-700 rounded-xl shadow-xl z-50 py-1">
              {PROVIDERS.map(p => (
                <button key={p.id}
                  onClick={() => { setProvider(p.id); setShowProv(false); send({ type: 'set_provider', provider: p.id }) }}
                  className={`w-full text-left px-4 py-2 text-sm hover:bg-gray-700 flex justify-between items-center transition-colors ${p.id === provider ? 'text-violet-400' : 'text-gray-300'}`}
                >
                  {p.label}
                  {p.free && <span className="text-xs text-green-400">free</span>}
                </button>
              ))}
            </div>
          )}
        </div>
      </header>

      {/* ── Main content + Canvas ── */}
      <div className="flex flex-1 overflow-hidden">

      {/* ── Messages ── */}
      <main className={`overflow-y-auto px-4 py-6 space-y-6 scrollbar-thin ${canvasOpen ? 'w-1/2' : 'flex-1'}`} onClick={() => setShowProv(false)}>
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-8 text-center">
            <div>
              <div className="w-16 h-16 rounded-2xl bg-violet-900/50 flex items-center justify-center mx-auto mb-4">
                <Globe size={32} className="text-violet-400" />
              </div>
              <h2 className="text-xl font-semibold text-white mb-2">AgenticWeb</h2>
              <p className="text-gray-400 text-sm max-w-md">
                Type a goal. I'll browse the web, extract data, and get it done — no clicking required.
              </p>
            </div>

            {/* Suggestions */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-2xl w-full">
              {SUGGESTIONS.map((s, i) => (
                <button key={i}
                  onClick={() => setInput(s)}
                  className="text-left text-sm text-gray-400 bg-gray-800/60 hover:bg-gray-800 border border-gray-700 hover:border-violet-600 rounded-xl px-4 py-3 transition-all"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map(msg => <Message key={msg.id} msg={msg} />)}
        <div ref={bottomRef} />
      </main>

      {/* ── Canvas sidebar ── */}
      {canvasOpen && canvasImg && (
        <aside className="w-1/2 border-l border-gray-800 bg-gray-900 flex flex-col">
          <div className="flex items-center justify-between px-4 py-2 border-b border-gray-800">
            <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Live Browser</span>
            <button onClick={() => setCanvasOpen(false)} className="text-gray-500 hover:text-gray-300 transition-colors" title="Close canvas">
              <Minimize2 size={14} />
            </button>
          </div>
          <div className="flex-1 overflow-hidden p-2">
            <img
              src={`data:image/jpeg;base64,${canvasImg}`}
              alt="Browser screenshot"
              className="w-full h-full object-contain rounded-lg border border-gray-700"
            />
          </div>
        </aside>
      )}
      </div>

      {/* ── Input ── */}
      <footer className="px-4 py-4 border-t border-gray-800 bg-gray-900">
        <div className="max-w-3xl mx-auto flex gap-3 items-end">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKey}
            placeholder="Type a goal… (Enter to send)"
            disabled={running || !connected}
            rows={1}
            className="flex-1 bg-gray-800 border border-gray-700 focus:border-violet-500 text-gray-100 placeholder-gray-500 rounded-xl px-4 py-3 text-sm resize-none outline-none transition-colors disabled:opacity-50"
            style={{ maxHeight: 120 }}
          />
          {running && (
            <button
              onClick={stop}
              disabled={!connected}
              title="Stop task"
              className="w-11 h-11 bg-red-600 hover:bg-red-500 disabled:bg-gray-700 disabled:text-gray-500 rounded-xl flex items-center justify-center transition-colors shrink-0"
            >
              <Square size={16} />
            </button>
          )}
          <button
            onClick={submit}
            disabled={running || !input.trim() || !connected}
            title="Send"
            className="w-11 h-11 bg-violet-600 hover:bg-violet-500 disabled:bg-gray-700 disabled:text-gray-500 rounded-xl flex items-center justify-center transition-colors shrink-0"
          >
            <Send size={16} />
          </button>
        </div>
        <p className="text-center text-xs text-gray-600 mt-2">
          AgenticWeb · LangGraph + MCP · Built for Microsoft Build Hackathon 2025
        </p>
      </footer>
    </div>
  )
}
