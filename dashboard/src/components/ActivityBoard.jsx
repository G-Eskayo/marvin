import { useEffect, useState } from 'react'
import ProjectBoard from './ProjectBoard.jsx'
import DashboardHome from './DashboardHome.jsx'
import ActivityBanner from './ActivityBanner.jsx'
import DeviceColumns from './DeviceColumns.jsx'
import NextUpQueue from './NextUpQueue.jsx'
import ParallelToggle from './ParallelToggle.jsx'

// The Activity tab is the project boards. What used to sit beside them lives where it belongs now:
// a ticket's pipeline history is the drill-down you click into on its card (ProjectBoard.jsx), and
// the autonomous agents' live status is in the Health tab ("Autonomous agents").
export default function ActivityBoard({ onOpenMr, onOpenDocs, onOpenTicket, onOpenProject, nav }) {
  const [view, setView] = useState('home')

  useEffect(() => {
    if (nav?.tab === 'activity' && nav.repo) {
      setView('board')
    }
  }, [nav?.at])

  return (
    <>
      <ActivityBanner />
      <DeviceColumns />
      <ParallelToggle />
      <NextUpQueue onOpenTicket={onOpenTicket} />
      {view === 'home' ? (
        <DashboardHome onOpenProject={onOpenProject} />
      ) : (
        <>
          <button onClick={() => setView('home')} className="mb-4 ml-6 text-sm text-neutral-400 hover:text-neutral-200">
            ← All projects
          </button>
          <ProjectBoard onOpenMr={onOpenMr} onOpenDocs={onOpenDocs} onOpenTicket={onOpenTicket} nav={nav} />
        </>
      )}
    </>
  )
}
