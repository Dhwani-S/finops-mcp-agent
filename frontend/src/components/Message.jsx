import { useState, Children, isValidElement } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import ToolEvent from './ToolEvent'
import ReasoningBlock from './ReasoningBlock'
import ChartView, { extractChartData } from './ChartView'
import './Message.css'

/**
 * Extract numbered options (1. Foo, 2. Bar …) from the agent's text.
 * Only matches lines that are PURELY a numbered option — not markdown bold items
 * like "1. **Gemini 2.5 Flash**: $24,004" which should render as rich content.
 */
function extractOptions(text) {
  if (!text) return { prose: text, options: [] }

  // Only match simple numbered lines that look like clickable options
  // (no markdown formatting, no colons with values, no long descriptions)
  const optionRe = /^\d+\.\s+(.+)$/gm
  const matches = [...text.matchAll(optionRe)]
  if (matches.length < 2) return { prose: text, options: [] }

  // If the numbered items contain markdown bold or dollar amounts, they are
  // rich content, not clickable options — let ReactMarkdown render them.
  const hasRichContent = matches.some(
    (m) => /\*\*/.test(m[1]) || /\$[\d,]+/.test(m[1])
  )
  if (hasRichContent) return { prose: text, options: [] }

  const options = matches.map((m, i) => ({ num: i + 1, label: m[1].trim() }))

  // Remove the numbered list from prose so it doesn't render twice
  let prose = text
  for (const m of matches) {
    prose = prose.replace(m[0], '')
  }
  prose = prose.replace(/\n{3,}/g, '\n\n').trim()

  return { prose, options }
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // fallback
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <button
      type="button"
      className={`copy-result-btn ${copied ? 'copied' : ''}`}
      onClick={handleCopy}
      title={copied ? 'Copied!' : 'Copy result'}
      aria-label={copied ? 'Copied!' : 'Copy result'}
    >
      {copied ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      )}
    </button>
  )
}

/* ── Max visible rows before truncation ── */
const TABLE_PREVIEW_ROWS = 10

/** Recursively extract text from React children (for CSV export). */
function textOf(node) {
  if (node == null) return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textOf).join('')
  if (isValidElement(node)) return textOf(node.props?.children)
  return ''
}

/** Download table data as CSV. */
function downloadTableCSV(thead, allRows) {
  const headerCells = thead?.props?.children?.props?.children
  const headers = Children.toArray(headerCells).map((c) => textOf(c))

  const csvRows = [headers.join(',')]
  for (const tr of allRows) {
    const cells = Children.toArray(tr.props?.children)
    csvRows.push(
      cells
        .map((c) => {
          const v = textOf(c)
          return v.includes(',') || v.includes('"') ? `"${v.replace(/"/g, '""')}"` : v
        })
        .join(',')
    )
  }
  const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'finops-table.csv'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** Markdown table with auto-collapse when rows exceed TABLE_PREVIEW_ROWS. */
function CollapsibleTable({ children, ...props }) {
  const [expanded, setExpanded] = useState(false)

  // children = [<thead>, <tbody>]
  const parts = Children.toArray(children)
  const thead = parts.find((c) => isValidElement(c) && c.type === 'thead')
  const tbody = parts.find((c) => isValidElement(c) && c.type === 'tbody')

  const allRows = tbody ? Children.toArray(tbody.props.children) : []
  const total = allRows.length
  // Only truncate if hiding at least 3 rows — hiding 1-2 rows is more annoying than helpful
  const needsTruncation = total > TABLE_PREVIEW_ROWS + 2

  const visibleRows = needsTruncation && !expanded ? allRows.slice(0, TABLE_PREVIEW_ROWS) : allRows

  return (
    <>
      <table {...props}>
        {thead}
        <tbody>{visibleRows}</tbody>
      </table>
      {needsTruncation && (
        <div className="table-overflow-bar">
          <span className="table-overflow-count">
            Showing {expanded ? total : TABLE_PREVIEW_ROWS} of {total} rows
          </span>
          <div className="table-overflow-actions">
            <button
              type="button"
              className="table-overflow-btn"
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? 'Show less' : `Show all ${total} rows`}
            </button>
            <button
              type="button"
              className="table-overflow-btn table-overflow-btn--download"
              onClick={() => downloadTableCSV(thead, allRows)}
              title="Download as CSV"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              CSV
            </button>
          </div>
        </div>
      )}
    </>
  )
}

export default function Message({ message, onOptionClick, disabled, chartMode }) {
  const { role, content, events, loading } = message
  const [showChart, setShowChart] = useState(false)

  if (role === 'user') {
    return (
      <div className="message message-user">
        <div className="message-content">{content}</div>
      </div>
    )
  }

  const { prose, options } = extractOptions(content)
  const chartDataList = extractChartData(events)
  const hasCharts = chartDataList.length > 0 && !loading

  return (
    <div className="message message-agent">
      {events && events.length > 0 && (
        <ReasoningBlock events={events} loading={loading} />
      )}
      {prose && (
        <div className="message-content">
          {!loading && content && (
            <CopyButton text={content} />
          )}
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              table({ node, children, ...props }) {
                return <CollapsibleTable {...props}>{children}</CollapsibleTable>
              },
              code({ node, inline, className, children, ...props }) {
                if (inline) {
                  return <code className="inline-code" {...props}>{children}</code>
                }
                return (
                  <pre className="code-block">
                    <code {...props}>{children}</code>
                  </pre>
                )
              },
              a({ href, children, ...props }) {
                if (href && href.startsWith('/api/reports/')) {
                  return (
                    <a href={href} download className="download-link" {...props}>
                      {children}
                    </a>
                  )
                }
                return <a href={href} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>
              }
            }}
          >
            {prose}
          </ReactMarkdown>
        </div>
      )}
      {options.length > 0 && (
        <div className="message-options" role="group" aria-label="Choose an option">
          {options.map((opt) => (
            <button
              key={opt.num}
              type="button"
              className="message-option-chip"
              disabled={disabled}
              onClick={() => onOptionClick?.(opt.label)}
            >
              <span className="message-option-num">{opt.num}</span>
              {opt.label}
            </button>
          ))}
        </div>
      )}
      {hasCharts && !chartMode && (
        <div className="chart-toggle-bar">
          <button
            type="button"
            className={`chart-toggle-btn ${showChart ? 'active' : ''}`}
            onClick={() => setShowChart((v) => !v)}
          >
            <span aria-hidden="true">📊</span> {showChart ? 'Hide Charts' : 'Show Charts'}
          </button>
        </div>
      )}
      {hasCharts && (chartMode || showChart) && chartDataList.map((cd, i) => (
        <ChartView key={i} chartData={cd} />
      ))}
      {loading && !content && (
        <div className="message-loading">
          <span className="dot" /><span className="dot" /><span className="dot" />
        </div>
      )}
    </div>
  )
}
