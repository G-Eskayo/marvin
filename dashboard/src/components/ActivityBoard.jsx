import { useState, useEffect } from 'react'
import DashboardHome from './DashboardHome.jsx'
import ProjectBoard from './ProjectBoard.jsx'
import ActivityBanner from './ActivityBanner.jsx'
import DeviceColumns from './DeviceColumns.jsx'
import NextUpQueue from './NextUpQueue.jsx'
import ParallelToggle from './ParallelToggle.jsx'

// The Activity tab is the project boards. What used to sit beside them lives where it belongs now:
// a ticket's pipeline history is the drill-down you click into on its card (ProjectBoard.jsx), and
// the autonomous agents' live status is in the Health tab ("Autonomous agents").
export default function ActivityBoard({ onOpenMr, onOpenDocs, onOpenTicket, nav }) {
  const [view, setView] = useState('home')
  const [synthesizedNav, setSynthesizedNav] = useState(null)

  useEffect(() => {
    if (nav?.tab === 'activity' && nav.repo) {
      setView('board')
    }
  }, [nav?.at])

  const handleOpenProject = (repo) => {
    setSynthesizedNav({ tab: 'activity', repo, at: Date.now() })
    setView('board')
  }

  const boardNav = synthesizedNav || nav

  return (
    <>
      <ActivityBanner />
      <DeviceColumns />
      <ParallelToggle />
      <NextUpQueue onOpenTicket={onOpenTicket} />
      {view === 'home' ? (
        <DashboardHome onOpenProject={handleOpenProject} />
      ) : (
        <>
          <div className="px-6 pt-4">
            <button onClick={() => { setView('home'); setSynthesizedNav(null) }} className="text-sm text-neutral-400 hover:text-neutral-200">
              ← All projects
            </button>
          </div>
          <ProjectBoard onOpenMr={onOpenMr} onOpenDocs={onOpenDocs} onOpenTicket={onOpenTicket} nav={boardNav} />
        </>
      )}
    </>
  )
}
