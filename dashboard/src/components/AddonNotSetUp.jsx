import React from 'react'

export function AddonNotSetUp({ addon, onEnable }) {
  const addonInfo = {
    portfolio: {
      name: 'Portfolio',
      description: 'Project portfolio and web updates'
    },
    resume_tailor: {
      name: 'Resume Tailor',
      description: 'Job application packages and resume tailoring'
    },
    seal_ingest: {
      name: 'Seal Ingest',
      description: 'Seal Speak beta feedback collection'
    }
  }

  // Own keys only: a name like "__proto__" or "constructor" must not find Object's built-ins and offer an Enable button
  const info = Object.hasOwn(addonInfo, addon) ? addonInfo[addon] : null
  if (!info) {
    return <div>Unknown add-on: {addon}</div>
  }

  return (
    <div className="addon-not-set-up">
      <div className="addon-header">
        <h2>{info.name}</h2>
        <p className="addon-description">{info.description}</p>
      </div>
      <div className="addon-message">
        <p>This add-on is not yet enabled.</p>
      </div>
      <div className="addon-actions">
        <button
          className="btn btn-primary"
          onClick={() => onEnable(addon)}
        >
          Enable Add-on
        </button>
        <p className="addon-help-text">
          Or edit <code>~/.agents/instance/instance.json</code> and set <code>features.{addon}</code> to <code>true</code>.
        </p>
      </div>
    </div>
  )
}
