import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import ToolEvent from './ToolEvent'
import ChartView, { extractChartData } from './ChartView'
import './Message.css'

/**
 * Extract numbered options (1. Foo, 2. Bar …) from the agent's text.
 * Returns { prose, options } where prose is the text before/after the list
 * and options is an array of { num, label } objects.
 */
function extractOptions(text) {
  if (!text) return { prose: text, options: [] }
  const optionRe = /^\d+\.\s+(.+)$/gm
  const matches = [...text.matchAll(optionRe)]
  if (matches.length < 2) return { prose: text, options: [] }

  const options = matches.map((m, i) => ({ num: i + 1, label: m[1].trim() }))

  // Remove the numbered list from prose so it doesn't render twice
  let prose = text
  for (const m of matches) {
    prose = prose.replace(m[0], '')
  }
  prose = prose.replace(/\n{3,}/g, '\n\n').trim()

  return { prose, options }
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
        <div className="message-events">
          {events.map((evt, i) => (
            <ToolEvent key={i} event={evt} />
          ))}
        </div>
      )}
      {prose && (
        <div className="message-content">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
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
