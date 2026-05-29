import { useEffect, useRef, useCallback, useState } from 'react'

const WS_BASE = import.meta.env.VITE_WS_URL || 'ws://127.0.0.1:8000'

export function useAgentSocket(sessionId, onEvent, onDisconnect) {
  const ws = useRef(null)
  const [connected, setConnected] = useState(false)
  const onEventRef = useRef(onEvent)
  const onDisconnectRef = useRef(onDisconnect)
  onEventRef.current = onEvent
  onDisconnectRef.current = onDisconnect

  const connect = useCallback(() => {
    if (ws.current?.readyState === WebSocket.OPEN) return
    const socket = new WebSocket(`${WS_BASE}/ws/${sessionId}`)

    socket.onopen = () => {
      setConnected(true)
      // ping keepalive every 25s
      socket._ping = setInterval(() => {
        if (socket.readyState === WebSocket.OPEN)
          socket.send(JSON.stringify({ type: 'ping' }))
      }, 25000)
    }

    socket.onmessage = (e) => {
      try { onEventRef.current(JSON.parse(e.data)) } catch (_) {}
    }

    socket.onclose = () => {
      setConnected(false)
      clearInterval(socket._ping)
      onDisconnectRef.current?.()
      // reconnect after 2s
      setTimeout(connect, 2000)
    }

    socket.onerror = () => socket.close()
    ws.current = socket
  }, [sessionId])

  useEffect(() => {
    connect()
    return () => {
      ws.current?.close()
      clearInterval(ws.current?._ping)
    }
  }, [connect])

  const send = useCallback((msg) => {
    if (ws.current?.readyState === WebSocket.OPEN)
      ws.current.send(JSON.stringify(msg))
  }, [])

  return { connected, send }
}
