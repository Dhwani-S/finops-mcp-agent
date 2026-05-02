import { useState, useRef, useEffect } from 'react'
import './ChatInput.css'

function Icon({ name, size = 16 }) {
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    'aria-hidden': 'true',
  }

  if (name === 'chart') {
    return (
      <svg {...common}>
        <path d="M4 19V5" />
        <path d="M4 19h16" />
        <rect x="7" y="11" width="3" height="5" rx="1" />
        <rect x="12" y="7" width="3" height="9" rx="1" />
        <rect x="17" y="9" width="3" height="7" rx="1" />
      </svg>
    )
  }

  if (name === 'csv') {
    return (
      <svg {...common}>
        <path d="M14 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7z" />
        <path d="M14 2v5h5" />
        <path d="M8 13h8" />
        <path d="M8 17h5" />
      </svg>
    )
  }

  if (name === 'excel') {
    return (
      <svg {...common}>
        <path d="M4 5a2 2 0 0 1 2-2h9l5 5v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" />
        <path d="M15 3v5h5" />
        <path d="M8 12h8" />
        <path d="M8 16h8" />
        <path d="M12 12v4" />
      </svg>
    )
  }

  return null
}

export default function ChatInput({
  onSend,
  onStop,
  isLoading,
  outputPrefs,
  onOutputPrefsChange,
  messages,
}) {
  const [text, setText] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const inputRef = useRef(null)
  const menuRef = useRef(null)

  useEffect(() => {
    if (!isLoading) inputRef.current?.focus()
  }, [isLoading])

  /* close menu on outside click */
  useEffect(() => {
    if (!menuOpen) return
    const handler = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [menuOpen])

  const handleSubmit = (e) => {
    e.preventDefault()
    if (text.trim() && !isLoading) {
      onSend(text)
      setText('')
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  /* ── Export helpers ─────────────────────────────── */

  /** Find the last agent message that has chartable table rows. */
  const getLastAssistantData = () => {
    if (!messages) return null
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i]
      if (m.role !== 'agent' && m.role !== 'assistant') continue

      for (let j = (m.events?.length || 0) - 1; j >= 0; j--) {
        const evt = m.events[j]
        if (evt?.type !== 'tool_result' || !evt.result) continue
        try {
          const parsed = JSON.parse(evt.result)
          const rows = Array.isArray(parsed) ? parsed : parsed?.values
          if (Array.isArray(rows) && rows.length) return { rows }
        } catch {
          /* ignore */
        }
      }

      // chart data is embedded as ```chart-data JSON blocks
      const match = m.content?.match(/```chart-data\s*\n([\s\S]*?)```/)
      if (match) {
        try { return JSON.parse(match[1]) } catch { /* ignore */ }
      }
    }
    return null
  }

  const triggerDownload = (blob, filename) => {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  const exportCSV = (silent) => {
    if (!silent) setMenuOpen(false)
    const data = getLastAssistantData()
    if (!data?.rows?.length) {
      if (!silent) alert('No table data in the latest response to export.')
      return
    }
    const headers = Object.keys(data.rows[0])
    const csvRows = [
      headers.join(','),
      ...data.rows.map((r) =>
        headers.map((h) => {
          const v = r[h] ?? ''
          return typeof v === 'string' && (v.includes(',') || v.includes('"'))
            ? `"${v.replace(/"/g, '""')}"`
            : v
        }).join(',')
      ),
    ]
    triggerDownload(new Blob([csvRows.join('\n')], { type: 'text/csv' }), 'finops-export.csv')
  }

  const exportExcel = (silent) => {
    if (!silent) setMenuOpen(false)
    const data = getLastAssistantData()
    if (!data?.rows?.length) {
      if (!silent) alert('No table data in the latest response to export.')
      return
    }
    // Build simple XLSX-compatible XML (Excel 2003 SpreadsheetML)
    const headers = Object.keys(data.rows[0])
    const xmlRows = data.rows.map((r) =>
      '<Row>' + headers.map((h) => {
        const v = r[h] ?? ''
        const type = typeof v === 'number' ? 'Number' : 'String'
        return `<Cell><Data ss:Type="${type}">${String(v).replace(/&/g,'&amp;').replace(/</g,'&lt;')}</Data></Cell>`
      }).join('') + '</Row>'
    ).join('')
    const xml = `<?xml version="1.0"?><?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
<Worksheet ss:Name="Export"><Table>
<Row>${headers.map((h) => `<Cell><Data ss:Type="String">${h}</Data></Cell>`).join('')}</Row>
${xmlRows}
</Table></Worksheet></Workbook>`
    triggerDownload(
      new Blob([xml], { type: 'application/vnd.ms-excel' }),
      'finops-export.xls'
    )
  }

  const togglePref = (key) => {
    onOutputPrefsChange?.((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  const hasAnyPref = outputPrefs.charts || outputPrefs.csv || outputPrefs.excel

  /* ── Auto-export when new table data arrives with active prefs ── */
  const prevMsgCountRef = useRef(messages?.length ?? 0)
  useEffect(() => {
    if (!messages) return
    const prevCount = prevMsgCountRef.current
    prevMsgCountRef.current = messages.length
    if (messages.length <= prevCount) return
    // New message arrived – check if it has table data and prefs are active
    if (!outputPrefs.csv && !outputPrefs.excel) return
    const data = getLastAssistantData()
    if (!data?.rows?.length) return
    if (outputPrefs.csv) exportCSV(true)
    if (outputPrefs.excel) exportExcel(true)
  }, [messages?.length])

  return (
    <div className="chat-input-wrap">
      {/* ── Active preferences chips ── */}
      {hasAnyPref && (
        <div className="chat-prefs-bar">
          {outputPrefs.charts && (
            <span className="chat-pref-chip" onClick={() => togglePref('charts')}>
              <Icon name="chart" size={12} /> Charts <span className="chip-x">×</span>
            </span>
          )}
          {outputPrefs.csv && (
            <span className="chat-pref-chip" onClick={() => togglePref('csv')}>
              <Icon name="csv" size={12} /> CSV <span className="chip-x">×</span>
            </span>
          )}
          {outputPrefs.excel && (
            <span className="chat-pref-chip" onClick={() => togglePref('excel')}>
              <Icon name="excel" size={12} /> Excel <span className="chip-x">×</span>
            </span>
          )}
        </div>
      )}
      <form className="chat-input" onSubmit={handleSubmit}>
        <div className="chat-input-field">
          <textarea
            ref={inputRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="For example: Give me last month's top ten Azure services by cost..."
            rows={1}
            disabled={isLoading}
            aria-label="Your question"
          />
        </div>

        {/* ── Options dropdown ── */}
        <div className="chat-input-menu-wrap" ref={menuRef}>
          <button
            type="button"
            className={`chat-input-btn chat-input-btn--menu ${menuOpen ? 'open' : ''} ${hasAnyPref ? 'has-active' : ''}`}
            onClick={() => setMenuOpen((v) => !v)}
            title="Output preferences"
            aria-label="Output preferences menu"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="8" cy="3" r="1.4" fill="currentColor" />
              <circle cx="8" cy="8" r="1.4" fill="currentColor" />
              <circle cx="8" cy="13" r="1.4" fill="currentColor" />
            </svg>
          </button>
          {menuOpen && (
            <div className="chat-input-menu">
              <button
                type="button"
                className={`chat-menu-item ${outputPrefs.charts ? 'active' : ''}`}
                onClick={() => togglePref('charts')}
              >
                <span className="chat-menu-icon"><Icon name="chart" /></span>
                <span className="chat-menu-label">Charts</span>
                <span className={`chat-menu-toggle ${outputPrefs.charts ? 'on' : ''}`} />
              </button>
              <button
                type="button"
                className={`chat-menu-item ${outputPrefs.csv ? 'active' : ''}`}
                onClick={() => togglePref('csv')}
              >
                <span className="chat-menu-icon"><Icon name="csv" /></span>
                <span className="chat-menu-label">CSV</span>
                <span className={`chat-menu-toggle ${outputPrefs.csv ? 'on' : ''}`} />
              </button>
              <button
                type="button"
                className={`chat-menu-item ${outputPrefs.excel ? 'active' : ''}`}
                onClick={() => togglePref('excel')}
              >
                <span className="chat-menu-icon"><Icon name="excel" /></span>
                <span className="chat-menu-label">Excel</span>
                <span className={`chat-menu-toggle ${outputPrefs.excel ? 'on' : ''}`} />
              </button>
            </div>
          )}
        </div>

        {isLoading ? (
          <button type="button" className="chat-input-btn chat-input-btn--stop" onClick={onStop}>
            <span className="chat-input-btn-icon stop-square" aria-hidden="true" />
            Stop
          </button>
        ) : (
          <button type="submit" className="chat-input-btn chat-input-btn--send" disabled={!text.trim()}>
            Ask
            <span className="chat-input-btn-icon send-arrow" aria-hidden="true" />
          </button>
        )}
      </form>
      <p className="chat-input-hint">
        <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> new line
      </p>
    </div>
  )
}
