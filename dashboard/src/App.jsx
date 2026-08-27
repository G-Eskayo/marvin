import { useState } from 'react'
import MetricsScorecard from '@components/MetricsScorecard.jsx'
import MrReview from '@components/MrReview.jsx'

const TABS = [
  { id: 'metrics', label: 'Metrics' },
  { id: 'mr-review', label: 'MR Review' }
]

export default function App() {
  const [activeTab, setActiveTab] = useState('metrics')

  return (
    <div className="flex h-screen flex-col">
      <header className="flex shrink-0 items-center gap-1 border-b border-neutral-800 px-6 pb-3 pt-12">
        <h1 className="mr-6 text-sm font-semibold tracking-wide text-neutral-400">MARVIN METRICS</h1>
        <nav className="flex gap-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
                activeTab === tab.id
                  ? 'bg-neutral-800 text-white'
                  : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="flex-1 overflow-auto">
        {activeTab === 'metrics' ? <MetricsScorecard /> : <MrReview />}
      </main>
    </div>
  )
}
