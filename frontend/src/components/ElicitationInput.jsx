import { useState, useRef, useEffect } from 'react'
import './ElicitationInput.css'

/**
 * ElicitationInput — Renders dynamic input controls based on type.
 *
 * Supported types:
 *   chips              — 2-7 short options, single select
 *   multi-chips        — 2-7 options, pick many
 *   dropdown           — 8+ options, single select
 *   multi-dropdown     — 8+ options, pick many (with checkboxes)
 *   searchable         — 50+ options, type-ahead autocomplete
 *   date-range         — from/to date pickers
 *   slider             — numeric range/threshold
 *   toggle             — yes/no binary
 *   text-input         — free-form text entry
 *   checkbox-list      — 4-15 visible options with checkboxes
 */

export default function ElicitationInput({ config, onSubmit, disabled, autoConfirm }) {
  const { type, label, options = [], placeholder, min, max, step, defaultValue } = config

  switch (type) {
    case 'chips':
      return <Chips label={label} options={options} onSubmit={onSubmit} disabled={disabled} />
    case 'multi-chips':
      return <MultiChips label={label} options={options} onSubmit={onSubmit} disabled={disabled} autoConfirm={autoConfirm} />
    case 'dropdown':
      return <Dropdown label={label} options={options} placeholder={placeholder} onSubmit={onSubmit} disabled={disabled} />
    case 'multi-dropdown':
      return <MultiDropdown label={label} options={options} placeholder={placeholder} onSubmit={onSubmit} disabled={disabled} />
    case 'searchable':
      return <Searchable label={label} options={options} placeholder={placeholder} onSubmit={onSubmit} disabled={disabled} />
    case 'date-range':
      return <DateRange label={label} onSubmit={onSubmit} disabled={disabled} defaultValue={defaultValue} />
    case 'slider':
      return <Slider label={label} min={min} max={max} step={step} defaultValue={defaultValue} onSubmit={onSubmit} disabled={disabled} />
    case 'toggle':
      return <Toggle label={label} options={options} onSubmit={onSubmit} disabled={disabled} />
    case 'text-input':
      return <TextInput label={label} placeholder={placeholder} onSubmit={onSubmit} disabled={disabled} />
    case 'checkbox-list':
      return <CheckboxList label={label} options={options} onSubmit={onSubmit} disabled={disabled} />
    default:
      return null
  }
}

/* ─────────────────────────────────────────────────────────────────────────── */
/* 1. Chips — single select                                                   */
/* ─────────────────────────────────────────────────────────────────────────── */
function Chips({ label, options, onSubmit, disabled }) {
  return (
    <div className="elicit elicit-chips">
      {label && <div className="elicit-label">{label}</div>}
      <div className="elicit-chip-group" role="group">
        {options.map((opt) => (
          <button
            key={opt}
            type="button"
            className="elicit-chip"
            disabled={disabled}
            onClick={() => onSubmit(opt)}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────── */
/* 2. Multi-Chips — multi select with Done button                             */
/* ─────────────────────────────────────────────────────────────────────────── */
function MultiChips({ label, options, onSubmit, disabled, autoConfirm }) {
  const [selected, setSelected] = useState(new Set())

  // Auto-submit when selection changes (used inside ElicitationGroup)
  useEffect(() => {
    if (autoConfirm && selected.size > 0) {
      onSubmit([...selected].join(', '))
    }
  }, [selected, autoConfirm])

  function toggle(opt) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(opt)) next.delete(opt)
      else next.add(opt)
      return next
    })
  }

  const allSelected = selected.size === options.length

  function toggleAll() {
    if (allSelected) setSelected(new Set())
    else setSelected(new Set(options))
  }

  return (
    <div className="elicit elicit-chips">
      {label && <div className="elicit-label">{label}</div>}
      <div className="elicit-chip-group" role="group">
        {options.length >= 3 && (
          <button
            type="button"
            className={`elicit-chip elicit-chip--all ${allSelected ? 'selected' : ''}`}
            disabled={disabled}
            onClick={toggleAll}
          >
            All
          </button>
        )}
        {options.map((opt) => (
          <button
            key={opt}
            type="button"
            className={`elicit-chip ${selected.has(opt) ? 'selected' : ''}`}
            disabled={disabled}
            onClick={() => toggle(opt)}
          >
            {opt}
          </button>
        ))}
      </div>
      {!autoConfirm && selected.size > 0 && (
        <button
          type="button"
          className="elicit-submit elicit-submit--confirm"
          disabled={disabled}
          onClick={() => onSubmit([...selected].join(', '))}
        >
          ✓ Confirm ({selected.size} selected)
        </button>
      )}
      {autoConfirm && selected.size > 0 && (
        <span className="elicit-auto-hint">{selected.size} selected</span>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────── */
/* 3. Dropdown — single select                                                */
/* ─────────────────────────────────────────────────────────────────────────── */
function Dropdown({ label, options, placeholder, onSubmit, disabled }) {
  const [value, setValue] = useState('')

  return (
    <div className="elicit elicit-dropdown">
      {label && <div className="elicit-label">{label}</div>}
      <div className="elicit-row">
        <select
          className="elicit-select"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={disabled}
        >
          <option value="">{placeholder || 'Select an option…'}</option>
          {options.map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
        <button
          type="button"
          className="elicit-submit"
          disabled={disabled || !value}
          onClick={() => onSubmit(value)}
        >
          Confirm
        </button>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────── */
/* 4. Multi-Dropdown — multi select with checkboxes                           */
/* ─────────────────────────────────────────────────────────────────────────── */
function MultiDropdown({ label, options, placeholder, onSubmit, disabled }) {
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState(new Set())
  const [filter, setFilter] = useState('')
  const wrapRef = useRef(null)

  useEffect(() => {
    function handleClick(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  function toggle(opt) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(opt)) next.delete(opt)
      else next.add(opt)
      return next
    })
  }

  const allSelected = selected.size === options.length
  function toggleAll() {
    if (allSelected) setSelected(new Set())
    else setSelected(new Set(options))
  }

  const filtered = filter
    ? options.filter((o) => o.toLowerCase().includes(filter.toLowerCase()))
    : options

  return (
    <div className="elicit elicit-multi-dropdown" ref={wrapRef}>
      {label && <div className="elicit-label">{label}</div>}
      <button
        type="button"
        className="elicit-dropdown-trigger"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      >
        {selected.size > 0
          ? `${selected.size} selected`
          : (placeholder || 'Select options…')}
        <span className="elicit-caret">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="elicit-dropdown-panel">
          <input
            type="text"
            className="elicit-dropdown-search"
            placeholder="Search…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            autoFocus
          />
          <label className="elicit-check-row elicit-check-all">
            <input type="checkbox" checked={allSelected} onChange={toggleAll} />
            <span>Select All</span>
          </label>
          <div className="elicit-dropdown-list">
            {filtered.map((opt) => (
              <label key={opt} className="elicit-check-row">
                <input
                  type="checkbox"
                  checked={selected.has(opt)}
                  onChange={() => toggle(opt)}
                />
                <span>{opt}</span>
              </label>
            ))}
            {filtered.length === 0 && (
              <div className="elicit-no-match">No matches</div>
            )}
          </div>
        </div>
      )}
      {selected.size > 0 && (
        <button
          type="button"
          className="elicit-submit"
          disabled={disabled}
          onClick={() => { onSubmit([...selected].join(', ')); setOpen(false) }}
        >
          Done ({selected.size} selected)
        </button>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────── */
/* 5. Searchable — autocomplete for large lists                               */
/* ─────────────────────────────────────────────────────────────────────────── */
function Searchable({ label, options, placeholder, onSubmit, disabled }) {
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(new Set())
  const [showSuggestions, setShowSuggestions] = useState(false)
  const wrapRef = useRef(null)

  useEffect(() => {
    function handleClick(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setShowSuggestions(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const filtered = query
    ? options.filter((o) => o.toLowerCase().includes(query.toLowerCase()))
    : options.slice(0, 20)

  function addItem(opt) {
    setSelected((prev) => new Set(prev).add(opt))
    setQuery('')
    setShowSuggestions(false)
  }

  function removeItem(opt) {
    setSelected((prev) => {
      const next = new Set(prev)
      next.delete(opt)
      return next
    })
  }

  return (
    <div className="elicit elicit-searchable" ref={wrapRef}>
      {label && <div className="elicit-label">{label}</div>}
      {selected.size > 0 && (
        <div className="elicit-tags">
          {[...selected].map((s) => (
            <span key={s} className="elicit-tag">
              {s}
              <button type="button" onClick={() => removeItem(s)} className="elicit-tag-x">×</button>
            </span>
          ))}
        </div>
      )}
      <input
        type="text"
        className="elicit-search-input"
        placeholder={placeholder || 'Type to search…'}
        value={query}
        disabled={disabled}
        onChange={(e) => { setQuery(e.target.value); setShowSuggestions(true) }}
        onFocus={() => setShowSuggestions(true)}
      />
      {showSuggestions && filtered.length > 0 && (
        <div className="elicit-suggestion-list">
          {filtered.map((opt) => (
            <button
              key={opt}
              type="button"
              className={`elicit-suggestion ${selected.has(opt) ? 'picked' : ''}`}
              onClick={() => addItem(opt)}
              disabled={selected.has(opt)}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
      {selected.size > 0 && (
        <button
          type="button"
          className="elicit-submit"
          disabled={disabled}
          onClick={() => onSubmit([...selected].join(', '))}
        >
          Done ({selected.size} selected)
        </button>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────── */
/* 6. Date Range                                                              */
/* ─────────────────────────────────────────────────────────────────────────── */
function DateRange({ label, onSubmit, disabled, defaultValue }) {
  const today = new Date().toISOString().slice(0, 10)
  const thirtyAgo = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10)
  const [from, setFrom] = useState(defaultValue?.from || thirtyAgo)
  const [to, setTo] = useState(defaultValue?.to || today)

  return (
    <div className="elicit elicit-date-range">
      {label && <div className="elicit-label">{label}</div>}
      <div className="elicit-date-row">
        <label className="elicit-date-field">
          <span>From</span>
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} disabled={disabled} />
        </label>
        <label className="elicit-date-field">
          <span>To</span>
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} disabled={disabled} />
        </label>
        <button
          type="button"
          className="elicit-submit"
          disabled={disabled}
          onClick={() => onSubmit(`From ${from} to ${to}`)}
        >
          Apply
        </button>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────── */
/* 7. Slider                                                                  */
/* ─────────────────────────────────────────────────────────────────────────── */
function Slider({ label, min = 0, max = 100, step = 1, defaultValue, onSubmit, disabled }) {
  const [value, setValue] = useState(defaultValue ?? Math.round((min + max) / 2))

  return (
    <div className="elicit elicit-slider">
      {label && <div className="elicit-label">{label}</div>}
      <div className="elicit-slider-row">
        <span className="elicit-slider-min">{min}</span>
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => setValue(Number(e.target.value))}
          disabled={disabled}
          className="elicit-range"
        />
        <span className="elicit-slider-max">{max}</span>
        <span className="elicit-slider-val">{value}</span>
      </div>
      <button
        type="button"
        className="elicit-submit"
        disabled={disabled}
        onClick={() => onSubmit(String(value))}
      >
        Confirm
      </button>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────── */
/* 8. Toggle — yes/no switch                                                  */
/* ─────────────────────────────────────────────────────────────────────────── */
function Toggle({ label, options, onSubmit, disabled }) {
  const optA = options?.[0] || 'Yes'
  const optB = options?.[1] || 'No'
  const [active, setActive] = useState(optA)

  return (
    <div className="elicit elicit-toggle">
      {label && <div className="elicit-label">{label}</div>}
      <div className="elicit-toggle-row">
        <button
          type="button"
          className={`elicit-toggle-btn ${active === optA ? 'active' : ''}`}
          disabled={disabled}
          onClick={() => setActive(optA)}
        >
          {optA}
        </button>
        <button
          type="button"
          className={`elicit-toggle-btn ${active === optB ? 'active' : ''}`}
          disabled={disabled}
          onClick={() => setActive(optB)}
        >
          {optB}
        </button>
      </div>
      <button
        type="button"
        className="elicit-submit"
        disabled={disabled}
        onClick={() => onSubmit(active)}
      >
        Confirm
      </button>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────── */
/* 9. Text Input                                                              */
/* ─────────────────────────────────────────────────────────────────────────── */
function TextInput({ label, placeholder, onSubmit, disabled }) {
  const [value, setValue] = useState('')

  function handleKey(e) {
    if (e.key === 'Enter' && value.trim()) {
      onSubmit(value.trim())
    }
  }

  return (
    <div className="elicit elicit-text-input">
      {label && <div className="elicit-label">{label}</div>}
      <div className="elicit-row">
        <input
          type="text"
          className="elicit-text"
          placeholder={placeholder || 'Type your answer…'}
          value={value}
          disabled={disabled}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKey}
        />
        <button
          type="button"
          className="elicit-submit"
          disabled={disabled || !value.trim()}
          onClick={() => onSubmit(value.trim())}
        >
          Submit
        </button>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────── */
/* 10. Checkbox List — visible list with checkboxes                           */
/* ─────────────────────────────────────────────────────────────────────────── */
function CheckboxList({ label, options, onSubmit, disabled }) {
  const [selected, setSelected] = useState(new Set())

  function toggle(opt) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(opt)) next.delete(opt)
      else next.add(opt)
      return next
    })
  }

  const allSelected = selected.size === options.length
  function toggleAll() {
    if (allSelected) setSelected(new Set())
    else setSelected(new Set(options))
  }

  return (
    <div className="elicit elicit-checkbox-list">
      {label && <div className="elicit-label">{label}</div>}
      <label className="elicit-check-row elicit-check-all">
        <input type="checkbox" checked={allSelected} onChange={toggleAll} disabled={disabled} />
        <span>Select All</span>
      </label>
      <div className="elicit-checkbox-items">
        {options.map((opt) => (
          <label key={opt} className="elicit-check-row">
            <input
              type="checkbox"
              checked={selected.has(opt)}
              onChange={() => toggle(opt)}
              disabled={disabled}
            />
            <span>{opt}</span>
          </label>
        ))}
      </div>
      {selected.size > 0 && (
        <button
          type="button"
          className="elicit-submit"
          disabled={disabled}
          onClick={() => onSubmit([...selected].join(', '))}
        >
          Done ({selected.size} selected)
        </button>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────── */
/* ElicitationGroup — multiple inputs, answers collected and sent together    */
/* ─────────────────────────────────────────────────────────────────────────── */
export function ElicitationGroup({ configs, onSubmit, disabled }) {
  const [answers, setAnswers] = useState({})

  function handleAnswer(idx, value) {
    setAnswers((prev) => ({ ...prev, [idx]: value }))
  }

  const answeredCount = Object.keys(answers).length
  const allAnswered = configs.every((_, i) => answers[i])

  function handleSubmitAll() {
    const parts = configs.map((cfg, i) => {
      const label = cfg.label || `Option ${i + 1}`
      return `${label}: ${answers[i]}`
    })
    onSubmit(parts.join(', '))
  }

  return (
    <div className="elicit-group">
      {configs.map((cfg, i) => {
        const answered = !!answers[i]
        const isMultiSelect = cfg.type === 'multi-chips' || cfg.type === 'multi-dropdown' || cfg.type === 'checkbox-list'
        const showCollapsed = answered && !isMultiSelect
        return (
          <div key={i} className={`elicit-group-item ${answered ? 'answered' : ''}`}>
            {showCollapsed ? (
              <div className="elicit elicit-answered">
                <div className="elicit-answered-row">
                  <span className="elicit-answered-label">{cfg.label || `Option ${i + 1}`}</span>
                  <span className="elicit-answered-value">{answers[i]}</span>
                  <button
                    type="button"
                    className="elicit-answered-change"
                    onClick={() => setAnswers((prev) => {
                      const next = { ...prev }
                      delete next[i]
                      return next
                    })}
                    disabled={disabled}
                  >
                    Change
                  </button>
                </div>
              </div>
            ) : (
              <ElicitationInput
                config={cfg}
                disabled={disabled}
                autoConfirm={isMultiSelect}
                onSubmit={(val) => handleAnswer(i, val)}
              />
            )}
          </div>
        )
      })}
      <div className="elicit-group-footer">
        <span className="elicit-group-status">
          {answeredCount} of {configs.length} answered
        </span>
        {allAnswered && (
          <button
            type="button"
            className="elicit-submit elicit-group-send"
            disabled={disabled}
            onClick={handleSubmitAll}
          >
            Send All →
          </button>
        )}
      </div>
    </div>
  )
}
