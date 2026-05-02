import { useState, useRef, useEffect } from 'react'
import './ScopeSelector.css'

export default function ScopeSelector({ scopes, activeScopeId, onSelect, onManage }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const active = scopes.find((s) => s.id === activeScopeId)

  return (
    <div className="scope-selector" ref={ref}>
      <button
        type="button"
        className={`scope-selector-trigger ${active ? 'has-scope' : ''}`}
        onClick={() => setOpen((v) => !v)}
        title={active ? `Scope: ${active.name}` : 'Set scope'}
      >
        <svg className="scope-selector-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <circle cx="12" cy="12" r="6" />
          <circle cx="12" cy="12" r="2" />
        </svg>
        <span className="scope-selector-label">
          {active ? active.name : 'No scope'}
        </span>
        <svg className="scope-selector-caret" width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
          <path d="M2.5 4 L5 6.5 L7.5 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className="scope-selector-dropdown">
          <button
            type="button"
            className={`scope-selector-option ${!activeScopeId ? 'active' : ''}`}
            onClick={() => { onSelect(null); setOpen(false) }}
          >
            <span className="scope-option-name">No scope</span>
            <span className="scope-option-desc">Ask without filters</span>
          </button>
          {scopes.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`scope-selector-option ${s.id === activeScopeId ? 'active' : ''}`}
              onClick={() => { onSelect(s.id); setOpen(false) }}
            >
              <span className="scope-option-name">{s.name}</span>
              <span className="scope-option-desc">
                {[
                  s.clouds.length && s.clouds.join(', '),
                  s.environments.length && s.environments.join(', '),
                  s.projects.length && `${s.projects.length} project(s)`,
                ].filter(Boolean).join(' · ') || 'No filters'}
              </span>
            </button>
          ))}
          <div className="scope-selector-divider" />
          <button
            type="button"
            className="scope-selector-option scope-selector-manage"
            onClick={() => { onManage(); setOpen(false) }}
          >
            <span className="scope-option-name">Manage scopes…</span>
          </button>
        </div>
      )}
    </div>
  )
}
