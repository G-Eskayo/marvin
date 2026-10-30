// MR Review by project (marvin#848), the look approved as the #767 prototype: one box per project, its header a single
// button (arrow and name alike collapse or expand it), the count, how many need you and what they are, then the cards
// under their tier headings. Pure rendering: the groups come from lib/mr_groups.js, the cards from the caller.
import { needsYouSummary, tierGroups } from '../lib/mr_groups.js'

export function GroupingToggle({ grouping, setGrouping }) {
  return (
    <div className="flex gap-1" role="group" aria-label="Group the open PRs">
      {[['project', 'By project'], ['all', 'All']].map(([id, label]) => (
        <button key={id} aria-pressed={grouping === id} onClick={() => setGrouping(id)}
          className={`rounded-md px-2.5 py-1 text-xs ${grouping === id ? 'bg-neutral-800 text-white' : 'text-neutral-400 hover:text-neutral-200'}`}>{label}</button>
      ))}
    </div>
  )
}

// Why a PR is under Other: said on its card so it gets fixed (mr_groups.js projectOfPr).
const OTHER_WHY = {
  'unknown-repo': 'Under Other: its repo isn’t in the project catalog.',
  'unknown-label': 'Under Other: its project: label names no project in the catalog.',
  'two-labels': 'Under Other: it has two different project: labels.'
}

export function HelperChip({ helper }) {
  if (!helper) return null
  const tone = helper.state === 'running' ? 'bg-indigo-950 text-indigo-200' : helper.state === 'failed' ? 'bg-red-950 text-red-300' : 'bg-emerald-950 text-emerald-300'
  return <span data-helper={helper.state} className={`mt-1 inline-block rounded px-1.5 py-0.5 text-xs ${tone}`}>{helper.label}</span>
}

export function ProjectGroup({ group, collapsed, onToggle, renderPr, statusOf }) {
  const empty = !group.count
  return (
    <section data-group={group.id} data-empty={empty ? '1' : undefined} className={`rounded-lg border border-neutral-800 ${empty ? 'opacity-60' : ''}`}>
      <button type="button" aria-expanded={!collapsed} onClick={() => onToggle(group)}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-left">
        <span aria-hidden="true" className="w-3 text-xs text-neutral-500">{collapsed ? '▸' : '▾'}</span>
        <span className={`text-base font-semibold ${empty ? 'text-neutral-300' : 'text-white'}`}>{group.name}</span>
        <span className="rounded-full bg-neutral-800 px-2 text-xs text-neutral-300">{group.count}</span>
        {group.needsYou > 0 && <span className="rounded-full bg-blue-950 px-2 text-xs text-blue-300">{group.needsYou} need{group.needsYou === 1 ? 's' : ''} you</span>}
        <span className="text-sm text-neutral-500">{needsYouSummary(group.prs)}</span>
      </button>
      {!collapsed && !empty && (
        <div className="px-4 pb-1">
          {tierGroups(group.prs, { statusOf }).map((tier) => (
            <div key={tier.id} data-tier={tier.id}>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-neutral-500">{tier.label}</h3>
              {tier.prs.map((pr) => (
                <div key={pr.key}>
                  {pr.groupWhy && <p className="mb-1 text-xs text-amber-400">{OTHER_WHY[pr.groupWhy]}</p>}
                  {renderPr(pr)}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
