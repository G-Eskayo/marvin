import ProjectBoard from './ProjectBoard.jsx'
import DeviceColumns from './DeviceColumns.jsx'
import NextUpQueue from './NextUpQueue.jsx'
import ParallelToggle from './ParallelToggle.jsx'

const SEVERITY_COLOR = {
  red: { bg: 'bg-red-950', border: 'border-red-900', dot: 'bg-red-500', text: 'text-red-300' },
}

// The Activity tab is the project boards. What used to sit beside them lives where it belongs now:
// a ticket's pipeline history is the drill-down you click into on its card (ProjectBoard.jsx), and
// the autonomous agents' live status is in the Health tab ("Autonomous agents").
export default function ActivityBoard({ onOpenMr, onOpenDocs, onOpenTicket, nav, healthStatus }) {
  const redChecks = healthStatus?.checks?.filter(c => c.severity === 'red' && ['pipeline:stopped', 'sync:stuck', 'deploy:missing'].some(id => c.id.startsWith(id))) || []

  if (redChecks.length === 0) {
    return (
      <>
        <DeviceColumns />
        <ParallelToggle />
        <NextUpQueue onOpenTicket={onOpenTicket} />
        <ProjectBoard onOpenMr={onOpenMr} onOpenDocs={onOpenDocs} onOpenTicket={onOpenTicket} nav={nav} />
      </>
    )
  }

  return (
    <>
      <div className={`p-4 border-b ${SEVERITY_COLOR.red.bg} ${SEVERITY_COLOR.red.border}`}>
        <div className="flex gap-2 items-start">
          <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${SEVERITY_COLOR.red.dot}`} />
          <div className={`flex-1 text-sm ${SEVERITY_COLOR.red.text}`}>
            {redChecks.map((check, idx) => (
              <div key={idx}>{check.detail}</div>
            ))}
          </div>
        </div>
      </div>
      <DeviceColumns />
      <ParallelToggle />
      <NextUpQueue onOpenTicket={onOpenTicket} />
      <ProjectBoard onOpenMr={onOpenMr} onOpenDocs={onOpenDocs} onOpenTicket={onOpenTicket} nav={nav} />
    </>
  )
}
