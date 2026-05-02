import { useState } from 'react'
import { CLOUD_OPTIONS, ENVIRONMENT_OPTIONS, createScope } from '../lib/scopes'
import './ScopeManager.css'

export default function ScopeManager({ scopes, onSave, onDelete, onClose }) {
  const [editing, setEditing] = useState(null) // null = list view, object = form

  const startNew = () =>
    setEditing({ name: '', clouds: [], projects: [], environments: [], owners: [], coreIds: [], freetext: '' })

  const startEdit = (scope) => setEditing({ ...scope })

  const handleSave = () => {
    if (!editing.name.trim()) return
    if (editing.id) {
      // update existing
      onSave(editing)
    } else {
      onSave(createScope(editing))
    }
    setEditing(null)
  }

  const toggleChip = (field, value) => {
    setEditing((prev) => {
      const arr = prev[field]
      return {
        ...prev,
        [field]: arr.includes(value) ? arr.filter((v) => v !== value) : [...arr, value],
      }
    })
  }

  const addTag = (field, value) => {
    const trimmed = value.trim()
    if (!trimmed) return
    setEditing((prev) => ({
      ...prev,
      [field]: prev[field].includes(trimmed) ? prev[field] : [...prev[field], trimmed],
    }))
  }

  const removeTag = (field, value) => {
    setEditing((prev) => ({
      ...prev,
      [field]: prev[field].filter((v) => v !== value),
    }))
  }

  // ── List View ──
  if (!editing) {
    return (
      <div className="scope-manager">
        <div className="scope-manager-header">
          <h3 className="scope-manager-title">Manage Scopes</h3>
          <button type="button" className="scope-manager-close" onClick={onClose}>×</button>
        </div>
        <p className="scope-manager-desc">
          Create named scopes to pre-filter your questions by cloud, project, environment, or owner.
        </p>
        <p className="scope-manager-note">
          💡 The agent may still ask clarifying questions (e.g. time period) even with a scope set.
        </p>
        <div className="scope-manager-list">
          {scopes.length === 0 && (
            <p className="scope-manager-empty">No scopes yet. Create one to get started.</p>
          )}
          {scopes.map((s) => (
            <div key={s.id} className="scope-manager-item">
              <div className="scope-manager-item-info">
                <span className="scope-manager-item-name">{s.name}</span>
                <span className="scope-manager-item-detail">
                  {[
                    s.clouds.length && s.clouds.join(', '),
                    s.projects.length && `${s.projects.length} project(s)`,
                    s.environments.length && s.environments.join(', '),
                    s.owners.length && `${s.owners.length} owner(s)`,
                  ]
                    .filter(Boolean)
                    .join(' · ') || 'No filters'}
                </span>
              </div>
              <div className="scope-manager-item-actions">
                <button type="button" className="scope-action-btn" onClick={() => startEdit(s)}>Edit</button>
                <button type="button" className="scope-action-btn scope-action-btn--danger" onClick={() => onDelete(s.id)}>Delete</button>
              </div>
            </div>
          ))}
        </div>
        <button type="button" className="scope-new-btn" onClick={startNew}>
          + New Scope
        </button>
      </div>
    )
  }

  // ── Form View ──
  return (
    <div className="scope-manager">
      <div className="scope-manager-header">
        <h3 className="scope-manager-title">{editing.id ? 'Edit Scope' : 'New Scope'}</h3>
        <button type="button" className="scope-manager-close" onClick={() => setEditing(null)}>×</button>
      </div>

      <div className="scope-form">
        <label className="scope-form-label">
          Name
          <input
            type="text"
            className="scope-form-input"
            value={editing.name}
            onChange={(e) => setEditing((p) => ({ ...p, name: e.target.value }))}
            placeholder="e.g. My Team Production"
            autoFocus
          />
        </label>

        <fieldset className="scope-form-fieldset">
          <legend className="scope-form-legend">Cloud Providers</legend>
          <div className="scope-form-chips">
            {CLOUD_OPTIONS.map((c) => (
              <button
                key={c}
                type="button"
                className={`scope-chip ${editing.clouds.includes(c) ? 'active' : ''}`}
                onClick={() => toggleChip('clouds', c)}
              >
                {c}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset className="scope-form-fieldset">
          <legend className="scope-form-legend">Environments</legend>
          <div className="scope-form-chips">
            {ENVIRONMENT_OPTIONS.map((e) => (
              <button
                key={e}
                type="button"
                className={`scope-chip ${editing.environments.includes(e) ? 'active' : ''}`}
                onClick={() => toggleChip('environments', e)}
              >
                {e}
              </button>
            ))}
          </div>
        </fieldset>

        <TagInput
          label="Projects"
          placeholder="Type project name and press Enter"
          tags={editing.projects}
          onAdd={(v) => addTag('projects', v)}
          onRemove={(v) => removeTag('projects', v)}
        />

        <TagInput
          label="Owners"
          placeholder="Type owner name and press Enter"
          tags={editing.owners}
          onAdd={(v) => addTag('owners', v)}
          onRemove={(v) => removeTag('owners', v)}
        />

        <TagInput
          label="Core IDs"
          placeholder="Type core ID and press Enter"
          tags={editing.coreIds || []}
          onAdd={(v) => addTag('coreIds', v)}
          onRemove={(v) => removeTag('coreIds', v)}
        />

        <label className="scope-form-label">
          Additional context (freetext)
          <input
            type="text"
            className="scope-form-input"
            value={editing.freetext}
            onChange={(e) => setEditing((p) => ({ ...p, freetext: e.target.value }))}
            placeholder="e.g. Only compute services, exclude dev"
          />
        </label>

        <div className="scope-form-actions">
          <button type="button" className="scope-save-btn" onClick={handleSave} disabled={!editing.name.trim()}>
            {editing.id ? 'Update' : 'Create'}
          </button>
          <button type="button" className="scope-cancel-btn" onClick={() => setEditing(null)}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}

function TagInput({ label, placeholder, tags, onAdd, onRemove }) {
  const [value, setValue] = useState('')

  const commit = () => {
    if (value.trim()) {
      onAdd(value)
      setValue('')
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      commit()
    }
  }

  return (
    <label className="scope-form-label">
      {label}
      <div className="scope-tag-wrap">
        {tags.map((t) => (
          <span key={t} className="scope-tag">
            {t}
            <button type="button" className="scope-tag-x" onClick={() => onRemove(t)}>×</button>
          </span>
        ))}
        <input
          type="text"
          className="scope-tag-input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={commit}
          placeholder={tags.length === 0 ? placeholder : ''}
        />
      </div>
    </label>
  )
}
