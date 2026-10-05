import ProjectBoard from './ProjectBoard.jsx'

// The Activity tab is the project boards. What used to sit beside them lives where it belongs now:
// a ticket's pipeline history is the drill-down you click into on its card (ProjectBoard.jsx), and
// the autonomous agents' live status is in the Health tab ("Autonomous agents").
export default function ActivityBoard({ onOpenMr, onOpenDocs, nav }) {
  return <ProjectBoard onOpenMr={onOpenMr} onOpenDocs={onOpenDocs} nav={nav} />
}
