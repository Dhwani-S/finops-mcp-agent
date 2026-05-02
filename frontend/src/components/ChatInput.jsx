import { useState, useRef, useEffect } from 'react'
import './ChatInput.css'

export default function ChatInput({
  onSend,
  onStop,
  isLoading,
  chartMode,
  onChartModeChange,
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

  /** Find the last assistant message that has chart data (table rows). */
  const getLastAssistantData = () => {
    if (!messages) return null
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i]
      if (m.role !== 'assistant') continue
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

  const exportCSV = () => {
    setMenuOpen(false)
    const data = getLastAssistantData()
    if (!data?.rows?.length) {
      alert('No table data in the latest response to export.')
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

  const exportExcel = () => {
    setMenuOpen(false)
    const data = getLastAssistantData()
    if (!data?.rows?.length) {
      alert('No table data in the latest response to export.')
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

  return (
    <div className="chat-input-wrap">
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
            className={`chat-input-btn chat-input-btn--menu ${menuOpen ? 'open' : ''} ${chartMode ? 'has-active' : ''}`}
            onClick={() => setMenuOpen((v) => !v)}
            title="Options"
            aria-label="Options menu"
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
                className={`chat-menu-item ${chartMode ? 'active' : ''}`}
                onClick={() => { onChartModeChange?.(!chartMode); setMenuOpen(false) }}
              >
                <span className="chat-menu-icon">📊</span>
                <span className="chat-menu-label">Charts</span>
                <span className={`chat-menu-toggle ${chartMode ? 'on' : ''}`} />
              </button>
              <div className="chat-menu-divider" />
              <button type="button" className="chat-menu-item" onClick={exportCSV}>
                <span className="chat-menu-icon">📥</span>
                <span className="chat-menu-label">Export CSV</span>
              </button>
              <button type="button" className="chat-menu-item" onClick={exportExcel}>
                <span className="chat-menu-icon">📊</span>
                <span className="chat-menu-label">Export Excel</span>
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
