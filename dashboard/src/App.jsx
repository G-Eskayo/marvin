import { useEffect, useState } from 'react'
import MetricsPage from '@components/MetricsPage.jsx'
import MrReview from '@components/MrReview.jsx'
import HealthDashboard from '@components/HealthDashboard.jsx'
import BootSequence from '@components/BootSequence.jsx'
import DocsExplorer from '@components/DocsExplorer.jsx'
import { warmDocs } from '@components/docs_warm.jsx'
import ActivityBoard from '@components/ActivityBoard.jsx'
import PortfolioHubGate from '@components/PortfolioHubGate.jsx'
import DispatchStatusBadge from '@components/DispatchStatusBadge.jsx'
import MarvinButton from '@components/MarvinButton.jsx'
import ActivityHover from '@components/ActivityHover.jsx'
import SupportTab from '@components/SupportTab.jsx'
import ItButton from '@components/ItButton.jsx'
import { visibleTabs } from './lib/tabs.js'
import { ScrollArea, useScrollArea } from '@components/ScrollPlaces.jsx'


const DOT_COLOR = {
  red: 'bg-red-500',
  blue: 'bg-blue-500',
  green: 'bg-emerald-500'
}

const STATUS_LABEL = {
  red: 'New PR(s) awaiting your first look',
  blue: 'Open PR(s), already seen, still awaiting approval',
  green: 'Nothing awaiting review'
}

// Refreshed on window.api.mr.onRefresh -- pushed the moment mr_raiser.py
// raises a PR (see webhook-server/refresh_relay.js + electron/main/
// refresh_server.js) -- so this is a safety net for whatever that push
// misses (Electron wasn't running yet when the ping arrived, the ping
// came from the other machine, etc.), not the primary update path.
const FALLBACK_POLL_MS = 120000

const HEALTH_DOT_COLOR = {
  red: 'bg-red-500',
  yellow: 'bg-amber-500',
  green: 'bg-emerald-500'
}

export default function App() {
  const [activeTab, setActiveTab] = useState('metrics')
  // Cross-tab links by project: { tab, ...target, at } -- the target tab reads what it needs
  // (prKey for MR Review, projectId for Docs, repo for Activity) and acts once per `at`.
  const [nav, setNav] = useState(null)
  const navigate = (tab, target = {}) => {
    setNav({ ...target, tab, at: Date.now() })
    setActiveTab(tab)
  }
  const [reviewStatus, setReviewStatus] = useState(null)
  const [healthOverall, setHealthOverall] = useState(null)
  const [support, setSupport] = useState({ role: null, badge: 0 })
  // Each tab, and each list or item inside it, opens where it was last left, or at its top (#755).
  const main = useScrollArea('main', activeTab)

  // Support link (ADR 0073): the role decides the tab or the IT button; the count comes from the saved cache and
  // refreshes when support.py rewrites it.
  useEffect(() => {
    const load = () => window.api.support?.state().then((s) => setSupport({ role: s.role, badge: s.badge })).catch(() => {})
    load()
    const offFocus = window.api.support?.onFocus?.((target) => navigate('support', target)) || (() => {})
    const offTrigger = window.api.triggers.on((t) => t.topic === 'support' && load())
    return () => { offFocus(); offTrigger() }
  }, [])

  // Docs speed budget (#570): pdf.js and the markdown renderer are warmed once, when the app is idle after boot.
  useEffect(() => warmDocs(), [])
  useEffect(() => {
    let cancelled = false
    async function refresh() {
      try {
        const result = await window.api.mr.reviewStatus()
        if (!cancelled) setReviewStatus(result)
      } catch {
        // Status dot is a nice-to-have -- a failed fetch just leaves the
        // last known state rather than surfacing an error anywhere.
      }
    }
    refresh()
    const interval = setInterval(refresh, FALLBACK_POLL_MS)
    const unsubscribe = window.api.mr.onRefresh(refresh)
    return () => {
      cancelled = true
      clearInterval(interval)
      unsubscribe()
    }
  }, [])

  useEffect(() => {
    if (activeTab !== 'mr-review') return
    window.api.mr
      .reviewStatus()
      .then(setReviewStatus)
      .catch(() => {})
  }, [activeTab])

  useEffect(() => {
    let cancelled = false
    function refreshHealthDot() {
      window.api.health
        .status()
        .then((result) => {
          if (!cancelled) setHealthOverall(result.overall)
        })
        .catch(() => {})
    }
    refreshHealthDot()
    const interval = setInterval(refreshHealthDot, 60_000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  return (
    <div className="flex h-screen flex-col">
      <BootSequence onNavigate={({ tab, ...target }) => navigate(tab, target)} />
      <header className="titlebar flex shrink-0 items-center gap-1 border-b border-neutral-800 px-6 pb-3 pt-12">
        <h1 className="mr-6 text-sm font-semibold tracking-wide text-neutral-400">MARVIN METRICS</h1>
        <nav className="flex gap-1">
          {visibleTabs(support.role).map((tab) => {
            const dot = tab.id === 'mr-review' ? reviewStatus?.status : tab.id === 'health' ? healthOverall : null
            const dotColorMap = tab.id === 'health' ? HEALTH_DOT_COLOR : DOT_COLOR
            const title = tab.id === 'mr-review' ? STATUS_LABEL[dot] : tab.id === 'health' && dot ? `Overall: ${dot}` : undefined
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                title={title}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors ${
                  activeTab === tab.id
                    ? 'bg-neutral-800 text-white'
                    : 'text-neutral-400 hover:text-neutral-200'
                }`}
              >
                {dot && <span className={`h-2 w-2 shrink-0 rounded-full ${dotColorMap[dot]}`} />}
                {tab.label}
                {tab.id === 'support' && support.badge > 0 && (
                  <span className="rounded-full bg-red-600 px-1.5 text-xs font-semibold text-white">{support.badge}</span>
                )}
              </button>
            )
          })}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <MarvinButton />
          {support.role === 'helped' && <ItButton onOpen={(r) => navigate('support', { repo: r.repo, number: r.number })} />}
          <ActivityHover>
            <DispatchStatusBadge onClick={() => navigate('health', { view: 'agents' })} />
          </ActivityHover>
        </div>
      </header>
      <main ref={main.ref} className="flex-1 overflow-auto">
        <ScrollArea value={main.area}>
          {activeTab === 'metrics' ? (
            <MetricsPage />
          ) : activeTab === 'mr-review' ? (
            <MrReview nav={nav} onOpenDocs={(projectId, path) => navigate('docs', { projectId, path })} onOpenBoard={(repo) => navigate('activity', { repo })} onOpenTicket={(repo, number) => navigate('activity', { repo, ticketNumber: number })} />
          ) : activeTab === 'health' ? (
            <HealthDashboard nav={nav} />
          ) : activeTab === 'docs' ? (
            <DocsExplorer nav={nav} onOpenBoard={(repo) => navigate('activity', { repo })} onOpenTicket={(repo, number) => navigate('activity', { repo, ticketNumber: number })} onOpenPr={(repo, number) => navigate('mr-review', { prKey: `${repo}#${number}` })} />
          ) : activeTab === 'support' ? (
            <SupportTab nav={nav} />
          ) : activeTab === 'portfolio' ? (
            <PortfolioHubGate />
          ) : (
            <ActivityBoard nav={nav} onOpenMr={(prKey) => navigate('mr-review', { prKey })} onOpenDocs={(projectId, path) => navigate('docs', { projectId, path })} onOpenTicket={(repo, number) => navigate('activity', { repo, ticketNumber: number })} onOpenProject={(repo) => navigate('activity', { repo })} />
          )}
        </ScrollArea>
      </main>
    </div>
  )
}
