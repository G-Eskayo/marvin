import { useState } from 'react'

const ADDON_INFO = {
  portfolio: {
    name: 'Portfolio',
    description: 'Build and maintain your professional portfolio. Integrates with your portfolio site to generate components, manage content, and preview changes.'
  },
  resume_tailor: {
    name: 'Resume Tailor',
    description: 'Generate tailored 1-page resumes from job descriptions. Maintains a master resume and creates application packages for each role.'
  },
  seal_ingest: {
    name: 'Seal Ingest',
    description: 'Collect and analyze beta feedback from Seal Speak TestFlight builds. Organizes reports by device and build, tracks metrics and user notes.'
  }
}

export function AddonNotSetUp({ addon, onEnable }) {
  const [loading, setLoading] = useState(false)
  const info = ADDON_INFO[addon] || { name: 'Unknown add-on', description: '' }

  async function handleEnable() {
    setLoading(true)
    try {
      await window.api.instance.setFeature(addon, true)
      onEnable?.()
    } catch (err) {
      console.error(`Failed to enable ${addon}:`, err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="addon-not-set-up">
      <div className="card">
        <h2>{info.name}</h2>
        <p className="description">{info.description}</p>

        <button
          onClick={handleEnable}
          disabled={loading}
          className="btn btn-primary"
        >
          {loading ? 'Setting up...' : 'Set up'}
        </button>

        <details className="manual-edit">
          <summary>Or set up manually</summary>
          <p>Edit <code>~/.agents/instance/instance.json</code> and set:</p>
          <pre><code>{`{
  "features": {
    "${addon}": true
  }
}`}</code></pre>
        </details>
      </div>

      <style jsx>{`
        .addon-not-set-up {
          padding: 1rem;
          max-width: 500px;
        }

        .card {
          border: 1px solid var(--color-border);
          border-radius: 8px;
          padding: 1.5rem;
          background: var(--color-bg-secondary);
        }

        h2 {
          margin: 0 0 0.5rem 0;
          font-size: 1.25rem;
        }

        .description {
          margin: 0 0 1.5rem 0;
          color: var(--color-text-secondary);
          line-height: 1.5;
        }

        .btn {
          padding: 0.5rem 1rem;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-size: 0.9rem;
          margin-bottom: 1rem;
        }

        .btn-primary {
          background: var(--color-primary);
          color: white;
        }

        .btn:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .manual-edit {
          margin-top: 1rem;
          padding: 1rem;
          background: var(--color-bg-tertiary);
          border-radius: 4px;
        }

        .manual-edit summary {
          cursor: pointer;
          font-weight: 500;
          margin-bottom: 0.5rem;
        }

        .manual-edit p {
          margin: 0.5rem 0;
          font-size: 0.85rem;
        }

        .manual-edit code {
          background: var(--color-bg-primary);
          padding: 0.2rem 0.4rem;
          border-radius: 3px;
          font-family: monospace;
        }

        .manual-edit pre {
          background: var(--color-bg-primary);
          padding: 0.75rem;
          border-radius: 4px;
          overflow-x: auto;
          margin: 0.5rem 0 0 0;
        }

        .manual-edit code {
          font-size: 0.8rem;
        }
      `}</style>
    </div>
  )
}
