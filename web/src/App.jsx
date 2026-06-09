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
  { id: 'github', label: 'GitHub Models - GPT-4o-mini (Microsoft)', free: true },
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
  { id: 'azure_openai', label: 'Azure OpenAI', free: false },
  { id: 'gemini', label: 'Gemma 4 31B IT', free: true },
  { id: 'groq', label: 'Groq Llama 3.3', free: true },
  { id: 'deepseek', label: 'DeepSeek V4 Flash', free: false },
  { id: 'claude', label: 'Claude Sonnet', free: false },
  { id: 'openai', label: 'GPT-4o Mini', free: false },
]

const SUGGESTIONS = [
  'Find cheapest flight BLR to GOA this Friday under Rs.4000',
  'What is the current gold price in India?',
  'Summarize top 5 Hacker News stories today',
  'Compare iPhone 16 Pro price on Flipkart vs Amazon India',
]

function StatusLine({ event }) {
  const icons = {
    status: <Loader size={12} className="animate-spin text-amber-500 shrink-0 mt-0.5" />,
    step: <CheckCircle size={12} className="text-emerald-500 shrink-0 mt-0.5" />,
    error: <AlertCircle size={12} className="text-red-500 shrink-0 mt-0.5" />,
  }
  return (
    <div className="flex gap-2 items-start font-mono text-[11px] text-slate-500 py-0.5">
      {icons[event.type] || null}
      <span>
        {event.type === 'step'
          ? `Step ${event.step} [${event.tool}] -> ${event.result?.slice(0, 100)}`
          : event.message || event.result?.slice(0, 120)}
      </span>
    </div>
  )
}

function Message({ msg }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex gap-3 items-start ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 shadow-sm ${isUser ? 'bg-sky-600 text-white' : 'bg-slate-100 text-slate-900 border border-slate-200'}`}>
        {isUser ? <User size={14} /> : <Bot size={14} />}
      </div>

      <div className={`max-w-[min(80%,720px)] rounded-xl px-4 py-3 text-sm leading-relaxed shadow-sm ${isUser ? 'bg-sky-600 text-white' : 'bg-white text-slate-800 border border-slate-200'}`}>
        {msg.logs?.length > 0 && (
          <div className="mb-3 space-y-0.5 border-b border-slate-200 pb-3">
            {msg.logs.map((e, i) => <StatusLine key={i} event={e} />)}
          </div>
        )}
        {msg.content && <p className="whitespace-pre-wrap">{msg.content}</p>}
        {msg.running && !msg.content && (
          <div className="flex gap-1.5 items-center text-slate-500 text-xs">
            <Loader size={12} className="animate-spin" />
            <span>Working...</span>
          </div>
        )}
      </div>
    </div>
  )
}

export default function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [provider, setProvider] = useState('github')
  const [showProviders, setShowProv] = useState(false)
  const [running, setRunning] = useState(false)
  const [health, setHealth] = useState(null)
  const [canvasImg, setCanvasImg] = useState(null)
  const [canvasOpen, setCanvasOpen] = useState(false)
  const [canvasActivity, setCanvasActivity] = useState('')
  const bottomRef = useRef(null)
  const inputRef = useRef(null)
  const currentMsgId = useRef(null)

  const updateCurrentAgent = useCallback((patch) => {
    setMessages(prev => {
      const targetId = currentMsgId.current ?? [...prev].reverse().find(m => m.role === 'agent' && m.running)?.id
      if (!targetId) return prev
      return prev.map(m => m.id === targetId ? { ...m, ...patch(m) } : m)
    })
  }, [])

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  useEffect(() => {
    fetch('/api/health').then(r => r.json()).then(setHealth).catch(() => {})
  }, [])

  const onEvent = useCallback((event) => {
    if (event.type === 'pong') return

    if (event.type === 'canvas') {
      setCanvasImg(event.data)
      setCanvasActivity('Live browser frame received')
      setCanvasOpen(true)
      return
    }

    if (event.type === 'status' && /^(Browsing|Clicking|Typing|Pressing|Waiting|Reading|Extracting)/.test(event.message || '')) {
      setCanvasActivity(event.message)
      setCanvasOpen(true)
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

    setMessages(prev => [...prev, { id: Date.now(), role: 'user', content: goal }])

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
    <div className="flex flex-col h-screen bg-slate-50 text-slate-900">
      <header className="flex items-center gap-3 px-4 sm:px-5 py-3 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="w-8 h-8 rounded-lg bg-slate-900 flex items-center justify-center shadow-sm">
          <Globe size={16} className="text-white" />
        </div>
        <div className="min-w-0">
          <h1 className="font-semibold text-sm text-slate-950">AgenticWeb</h1>
          <p className="text-xs text-slate-500 truncate">LangGraph + MCP autonomous web agent</p>
        </div>

        <div className="ml-auto hidden sm:flex items-center gap-2 rounded-full border border-slate-200 px-2.5 py-1">
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-500' : 'bg-red-500'}`} />
          <span className="text-xs text-slate-500">{connected ? 'connected' : 'reconnecting...'}</span>
        </div>

        {(canvasImg || canvasActivity) && (
          <button
            onClick={() => setCanvasOpen(v => !v)}
            className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border transition-colors ${canvasOpen ? 'bg-slate-900 border-slate-900 text-white' : 'bg-white border-slate-200 text-slate-600 hover:border-slate-300 hover:text-slate-900'}`}
            title={canvasOpen ? 'Close canvas' : 'Open canvas'}
          >
            <Maximize2 size={12} />
            <span className="hidden sm:inline">{canvasOpen ? 'Hide' : 'Canvas'}</span>
          </button>
        )}

        <div className="relative">
          <button
            onClick={() => setShowProv(v => !v)}
            className="flex items-center gap-2 text-xs bg-white hover:bg-slate-50 px-3 py-1.5 rounded-lg border border-slate-200 transition-colors shadow-sm"
          >
            <Zap size={12} className="text-amber-500" />
            <span className="text-slate-700 hidden sm:inline">{currentProvider?.label}</span>
            {currentProvider?.free && <span className="text-emerald-600 text-[10px]">free</span>}
            <ChevronDown size={12} className="text-slate-400" />
          </button>

          {showProviders && (
            <div className="absolute right-0 top-10 w-72 max-w-[calc(100vw-2rem)] max-h-[calc(100vh-5.5rem)] overflow-y-auto overscroll-contain bg-white border border-slate-200 rounded-xl shadow-xl z-50 py-1 scrollbar-thin">
              {PROVIDERS.map(p => (
                <button key={p.id}
                  onClick={() => { setProvider(p.id); setShowProv(false); send({ type: 'set_provider', provider: p.id }) }}
                  className={`w-full text-left px-4 py-2.5 text-sm hover:bg-slate-50 flex gap-3 justify-between items-center transition-colors ${p.id === provider ? 'text-slate-950 font-medium' : 'text-slate-600'}`}
                >
                  <span className="min-w-0 truncate">{p.label}</span>
                  {p.free && <span className="text-xs text-emerald-600 shrink-0">free</span>}
                </button>
              ))}
            </div>
          )}
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <main className={`overflow-y-auto px-4 py-6 space-y-6 scrollbar-thin ${canvasOpen ? 'hidden lg:block lg:w-1/2' : 'flex-1'}`} onClick={() => setShowProv(false)}>
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center min-h-full gap-8 text-center">
              <div>
                <div className="w-16 h-16 rounded-2xl bg-white border border-slate-200 flex items-center justify-center mx-auto mb-4 shadow-sm">
                  <Globe size={30} className="text-slate-900" />
                </div>
                <h2 className="text-2xl font-semibold text-slate-950 mb-2">What should we handle?</h2>
                <p className="text-slate-500 text-sm max-w-md">
                  Give AgenticWeb a goal. It can browse, extract, compare, and report back while you stay in flow.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-2xl w-full">
                {SUGGESTIONS.map((s, i) => (
                  <button key={i}
                    onClick={() => setInput(s)}
                    className="text-left text-sm text-slate-600 bg-white hover:bg-slate-50 border border-slate-200 hover:border-slate-300 rounded-xl px-4 py-3 transition-all shadow-sm"
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

        {canvasOpen && (canvasImg || canvasActivity) && (
          <aside className="w-full lg:w-1/2 border-l border-slate-200 bg-white flex flex-col">
            <div className="flex items-center justify-between px-4 py-2 border-b border-slate-200">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Live Browser</span>
              <button onClick={() => setCanvasOpen(false)} className="text-slate-400 hover:text-slate-900 transition-colors" title="Close canvas">
                <Minimize2 size={14} />
              </button>
            </div>
            <div className="flex-1 overflow-hidden p-3 bg-slate-100">
              {canvasImg ? (
                <img
                  src={`data:image/jpeg;base64,${canvasImg}`}
                  alt="Browser screenshot"
                  className="w-full h-full object-contain rounded-lg border border-slate-200 bg-white"
                />
              ) : (
                <div className="w-full h-full rounded-lg border border-slate-200 bg-white flex items-center justify-center px-6 text-center">
                  <div className="space-y-2">
                    <Loader size={18} className="animate-spin mx-auto text-amber-500" />
                    <p className="text-sm font-medium text-slate-700">{canvasActivity || 'Starting browser...'}</p>
                    <p className="text-xs text-slate-400">Waiting for the first remote Chromium frame.</p>
                  </div>
                </div>
              )}
            </div>
          </aside>
        )}
      </div>

      <footer className="px-4 py-4 border-t border-slate-200 bg-white">
        <div className="max-w-3xl mx-auto flex gap-3 items-end">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKey}
            placeholder="Type a goal... (Enter to send)"
            disabled={running || !connected}
            rows={1}
            className="flex-1 bg-slate-50 border border-slate-200 focus:border-slate-400 text-slate-900 placeholder-slate-400 rounded-xl px-4 py-3 text-sm resize-none outline-none transition-colors disabled:opacity-50"
            style={{ maxHeight: 120 }}
          />
          {running && (
            <button
              onClick={stop}
              disabled={!connected}
              title="Stop task"
              className="w-11 h-11 bg-red-600 hover:bg-red-500 disabled:bg-slate-200 disabled:text-slate-400 text-white rounded-xl flex items-center justify-center transition-colors shrink-0"
            >
              <Square size={16} />
            </button>
          )}
          <button
            onClick={submit}
            disabled={running || !input.trim() || !connected}
            title="Send"
            className="w-11 h-11 bg-slate-900 hover:bg-slate-700 disabled:bg-slate-200 disabled:text-slate-400 text-white rounded-xl flex items-center justify-center transition-colors shrink-0"
          >
            <Send size={16} />
          </button>
        </div>
        <p className="text-center text-xs text-slate-400 mt-2">
          AgenticWeb + LangGraph + MCP + Built for Microsoft Build Hackathon 2025
        </p>
      </footer>
    </div>
  )
}
