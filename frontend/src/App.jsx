import { useState, useRef, useEffect, useCallback } from 'react'
import ChatInput from './components/ChatInput'
import MessageList from './components/MessageList'
import StatusBar from './components/StatusBar'
import LeftRail from './components/LeftRail'
import {
  loadPersisted,
  savePersisted,
  createSession,
  titleFromMessages,
  THEME_STORAGE_KEY,
} from './lib/chatSessions'
import './App.css'

function App() {
  const persisted = useRef(null)
  if (!persisted.current) {
    persisted.current = loadPersisted()
  }

  const [sessions, setSessions] = useState(() => persisted.current.sessions)
  const [activeSessionId, setActiveSessionId] = useState(() => persisted.current.activeSessionId)
  const [isLoading, setIsLoading] = useState(false)
  const [status, setStatus] = useState(null)
  const [statusUpdatedAt, setStatusUpdatedAt] = useState(null)
  const [theme, setTheme] = useState(() => {
    try {
      const t = localStorage.getItem(THEME_STORAGE_KEY)
      return t === 'light' || t === 'dark' ? t : 'dark'
    } catch {
      return 'dark'
    }
  })

  const messages =
    sessions.find((s) => s.id === activeSessionId)?.messages ?? []


  const abortRef = useRef(null)
  const activeSessionIdRef = useRef(activeSessionId)
  useEffect(() => {
    activeSessionIdRef.current = activeSessionId
  }, [activeSessionId])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme)
    } catch {
      /* ignore */
    }
  }, [theme])

  useEffect(() => {
    savePersisted(sessions, activeSessionId)
  }, [sessions, activeSessionId])

  const refreshStatus = useCallback(() => {
    fetch('/api/status')
      .then((r) => r.json())
      .then((d) => {
        setStatus(d)
        setStatusUpdatedAt(new Date())
      })
      .catch(() => setStatus(null))
  }, [])

  useEffect(() => {
    refreshStatus()
  }, [refreshStatus])

  const updateActiveMessages = useCallback((updater) => {
    const sid = activeSessionIdRef.current
    setSessions((prev) =>
      prev.map((s) => {
        if (s.id !== sid) return s
        const nextMessages = typeof updater === 'function' ? updater(s.messages) : updater
        return {
          ...s,
          messages: nextMessages,
          updatedAt: Date.now(),
          title: titleFromMessages(nextMessages),
        }
      }),
    )
  }, [])

  const handleSSEEvent = (eventType, data) => {
    updateActiveMessages((prev) => {
      const updated = [...prev]
      const lastIdx = updated.length - 1
      const last = updated[lastIdx]
      if (!last || last.role !== 'agent') return updated

      // Deep-clone the message so StrictMode double-invocation doesn't duplicate
      const msg = { ...last, events: [...(last.events || [])] }

      switch (eventType) {
        case 'thinking':
          msg.events = [...msg.events, { type: 'thinking', message: data.message }]
          break
        case 'tool_call':
          msg.events = [...msg.events,
            { type: 'tool_call', tool: data.tool, server: data.server, args: data.args }]
          break
        case 'tool_result':
          msg.events = [...msg.events,
            { type: 'tool_result', tool: data.tool, result: data.result, chars: data.chars }]
          break
        case 'text':
          msg.content = data.content
          break
        case 'error':
          msg.content = `Error: ${data.message}`
          msg.loading = false
          break
        case 'done':
          msg.loading = false
          break
      }
      updated[lastIdx] = msg
      return updated
    })
  }

  const handleSend = async (text) => {
    if (!text.trim() || isLoading) return

    const userMsg = { role: 'user', content: text }
    const agentMsg = { role: 'agent', content: '', events: [], loading: true }
    updateActiveMessages((prev) => [...prev, userMsg, agentMsg])
    setIsLoading(true)

    try {
      abortRef.current = new AbortController()
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
        signal: abortRef.current.signal,
      })

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let pendingEvent = 'unknown'

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) {
            pendingEvent = 'unknown'
            continue
          }
          if (trimmed.startsWith('event:')) {
            pendingEvent = trimmed.slice(6).trim()
            continue
          }
          if (trimmed.startsWith('data:')) {
            const dataStr = trimmed.slice(5).trim()
            if (dataStr === '[DONE]') continue
            try {
              const data = JSON.parse(dataStr)
              handleSSEEvent(pendingEvent, data)
            } catch {
              /* skip malformed JSON */
            }
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        updateActiveMessages((prev) => {
          const copy = [...prev]
          const last = copy[copy.length - 1]
          if (last?.role === 'agent') {
            last.content = `Error: ${err.message}`
            last.loading = false
          }
          return copy
        })
      }
    } finally {
      setIsLoading(false)
      updateActiveMessages((prev) => {
        const copy = [...prev]
        const last = copy[copy.length - 1]
        if (last?.role === 'agent') last.loading = false
        return copy
      })
      refreshStatus()
    }
  }

  const handleClear = async () => {
    await fetch('/api/clear', { method: 'POST' })
    updateActiveMessages(() => [])
  }

  const handleExport = async () => {
    if (messages.length === 0) return
    const lines = []
    for (const msg of messages) {
      if (msg.role === 'user') {
        lines.push(`**User:** ${msg.content}`)
        lines.push('')
      } else if (msg.role === 'agent') {
        if (msg.events?.length) {
          for (const evt of msg.events) {
            if (evt.type === 'tool_call') {
              lines.push(`> Tool: ${evt.tool} (${evt.server})`)
              if (evt.args) lines.push(`> Args: ${JSON.stringify(evt.args, null, 2)}`)
            } else if (evt.type === 'tool_result') {
              lines.push(`> Result (${evt.chars} chars): ${evt.result?.slice(0, 500) || ''}`)
            }
          }
          lines.push('')
        }
        if (msg.content) {
          lines.push(`**Agent:** ${msg.content}`)
          lines.push('')
        }
      }
      lines.push('---')
      lines.push('')
    }
    const text = lines.join('\n')
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      /* fallback for older browsers */
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
  }

  const handleNewSession = async () => {
    await fetch('/api/clear', { method: 'POST' })
    const s = createSession()
    setSessions((prev) => [s, ...prev])
    setActiveSessionId(s.id)
  }

  const handleSelectSession = async (id) => {
    if (id === activeSessionId) return
    await fetch('/api/clear', { method: 'POST' })
    setActiveSessionId(id)
  }

  const handleDeleteSession = async (id) => {
    const remaining = sessions.filter((s) => s.id !== id)
    if (remaining.length === 0) {
      await fetch('/api/clear', { method: 'POST' })
      const s = createSession()
      setSessions([s])
      setActiveSessionId(s.id)
      return
    }
    if (id === activeSessionId) {
      await fetch('/api/clear', { method: 'POST' })
      const next = remaining[0]
      setActiveSessionId(next.id)
    }
    setSessions(remaining)
  }

  const handleStop = () => {
    abortRef.current?.abort()
    setIsLoading(false)
  }

  return (
    <div className="app-shell">
      <LeftRail
        status={status}
        theme={theme}
        onThemeChange={setTheme}
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={handleSelectSession}
        onNewSession={handleNewSession}
        onDeleteSession={handleDeleteSession}
      />
      <div className="app-chat-wrap">
        <div className="app">
          <header className="app-header">
            <div className="app-header-main">
              <h1 className="app-title">
                <span className="app-title-mark" aria-hidden="true" />
                FinOps insights
              </h1>
              <p className="app-tagline">
                Plain-language questions about cloud spend—breakdowns, trends, anomalies, and savings ideas.
              </p>
            </div>
            <StatusBar status={status} statusUpdatedAt={statusUpdatedAt} onClear={handleClear} onExport={handleExport} hasMessages={messages.length > 0} />
          </header>
          <main className="app-main">
            <MessageList
              key={activeSessionId}
              messages={messages}
              onSuggestion={handleSend}
              suggestionsDisabled={isLoading}
            />
          </main>
          <footer className="app-footer">
            <ChatInput
              onSend={handleSend}
              onStop={handleStop}
              isLoading={isLoading}
            />
          </footer>
        </div>
      </div>
    </div>
  )
}

export default App
