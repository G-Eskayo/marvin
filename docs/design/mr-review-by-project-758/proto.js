// MR Review by project, the prototype (marvin#758). Draws the real open PRs (data.local.js, from snapshot.mjs) with the
// real grouping and sorting (dashboard/src/lib/mr_groups.js) and the real card states (prState.js). Every option the
// Decisions ask about is a control here, and the whole screen is a function of the URL hash, so a screenshot is a URL.
import { groupPrs, allView, needsYouSummary, isCollapsed, toggleCollapsed, tierOf, helperFor, placeValue, historyItem, TIERS, OTHER } from '../../../dashboard/src/lib/mr_groups.js'
import { describePrState } from '../../../dashboard/src/lib/prState.js'
import { displayTitle } from '../../../dashboard/src/lib/pr_title.js'

// Proposed friendly names (decision "names"); the helper tabs already use these.
const FRIENDLY = {
  marvin: 'MARVIN', 'clarity-captions': 'Seal Speak', 'portfolio-website-updater': 'Portfolio', 'marvin-mobile': 'MARVIN Mobile',
  'marvin-voice': 'MARVIN Voice', 'marvin-instance': 'MARVIN instance', 'resume-tailor': 'Resume tailor', 'finance-os': 'Finance OS'
}
const DEFAULTS = { view: 'project', empty: 'hide', collapse: 'quiet', names: 'friendly', sortall: '0', examples: '0', focus: '', tap: 'collapse', width: '', closed: '0' }

const snap = window.SNAPSHOT
const state = () => ({ ...DEFAULTS, ...Object.fromEntries(new URLSearchParams(location.hash.slice(1))) })
const setState = (patch) => { location.hash = new URLSearchParams({ ...state(), ...patch }).toString() }
let saved = {} // collapse choices, as the real tab would keep them in saved_state

// Edge cases the live list doesn't have right now, clearly marked as examples.
function examples(projects) {
  const base = { example: true, checks: { state: 'passing', failing: [], pending: [] }, labels: [], isDraft: false, waitingOn: [], decisions: { pending: [], problems: [] } }
  const big = Array.from({ length: 12 }, (_, i) => ({
    ...base, number: 300 + i, repo: 'G-Eskayo/example-big', key: `G-Eskayo/example-big#${300 + i}`, title: `Example: one of twelve open MRs (${i + 1})`,
    ...(i < 2 ? {} : i < 6 ? { checks: { state: 'pending', failing: [], pending: ['test'] } } : i < 9 ? { waitingOn: [{ number: 300, shared: ['a.js'] }] } : { isDraft: true })
  }))
  const other = { ...base, number: 12, repo: 'someone/unregistered-repo', key: 'someone/unregistered-repo#12', title: 'Example: a PR from a repo the catalog doesn’t know' }
  const typo = { ...base, number: 799, repo: 'G-Eskayo/marvin', key: 'G-Eskayo/marvin#799', title: 'Example: labelled project:portfolo (a typo)', labels: ['project:portfolo'] }
  return { prs: [...big, other, typo], projects: [...projects, { id: 'example-big', name: 'Example: a big project', repo: 'G-Eskayo/example-big', status: 'active' }] }
}

function data(s) {
  let projects = snap.projects.map((p) => ({ ...p, name: s.names === 'friendly' ? FRIENDLY[p.id] || p.name : p.name }))
  let prs = snap.prs
  if (s.examples === '1') {
    const ex = examples(projects)
    projects = ex.projects
    prs = [...prs, ...ex.prs]
  }
  return { projects, prs }
}

const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag)
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v)
    else if (v != null && v !== false) el.setAttribute(k, v === true ? '' : v)
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid)
  return el
}

const TONE = { ready: 'ready', working: 'working', wait: 'wait', blocked: 'blocked' }
const WHY = { 'unknown-repo': 'its repo isn’t in the project catalog', 'unknown-label': 'its project: label names no project', 'two-labels': 'it has two project: labels' }

function card(pr, names, homeRepo = 'G-Eskayo/marvin') {
  const d = describePrState(pr)
  const helper = helperFor(pr, names, snap.tabs)
  return h('div', { class: `card ${pr.example ? 'example' : ''}` },
    h('div', { class: 'card-top' },
      h('div', { class: 'card-main' },
        h('p', { class: 'title' }, `#${pr.number} — ${displayTitle(pr.title)}`, ' ',
          pr.repo !== homeRepo && h('span', { class: 'chip repo' }, pr.repo.split('/')[1]),
          pr.isDraft && h('span', { class: 'chip draft' }, 'draft')),
        h('p', { class: `headline tone-${TONE[d.tone] || 'wait'}` }, pr.isDraft ? `Draft · ${d.headline}` : d.headline),
        pr.groupWhy && h('p', { class: 'why' }, `In Other because ${WHY[pr.groupWhy]}.`),
        helper && h('p', { class: `helper helper-${helper.state}` }, helper.label)),
      h('div', { class: 'actions' },
        d.approve !== 'hidden' && h('button', { class: 'approve', disabled: d.approve === 'disabled' }, 'Approve'),
        d.deny !== 'hidden' && h('button', { class: 'deny' }, 'Deny'))))
}

function list(prs, namesOf, homeRepo) {
  const out = []
  let last = null
  for (const pr of prs) {
    const t = tierOf(pr)
    if (t !== last) out.push(h('p', { class: 'tier' }, TIERS.find((x) => x.id === t).label))
    last = t
    out.push(card(pr, namesOf(pr), homeRepo))
  }
  return out
}

function render() {
  const s = state()
  document.documentElement.style.setProperty('--w', s.width ? `${s.width}px` : '100%')
  const { projects, prs } = data(s)
  const namesById = (id) => { const p = projects.find((x) => x.id === id); return [id, p?.name, FRIENDLY[id]].filter(Boolean) }
  // Inside a group the repo chip only shows when a PR isn't in its project's own repo (a project: label).
  const repoOf = (id) => projects.find((x) => x.id === id)?.repo || null
  const opts = { rule: s.collapse, limit: 8 }
  const groups = groupPrs(prs, projects, { empty: s.empty, isLive: (p) => p.status === 'active' })
  // closed=1: as if you had collapsed every group (to see the whole list of groups in one screenshot).
  if (s.closed === '1' && !Object.keys(saved).length) saved = Object.fromEntries(groups.map((g) => [g.id, true]))
  const focus = s.view === 'project' && s.focus ? groups.find((g) => g.id === s.focus) : null
  const app = document.getElementById('app')
  app.replaceChildren()

  app.append(
    h('div', { class: 'tabs' }, ...['Metrics', 'MR Review', 'Health', 'Docs', 'Activity', 'Portfolio'].map((t) => h('span', { class: t === 'MR Review' ? 'on' : '' }, t))),
    h('div', { class: 'toggle' },
      h('button', { 'aria-pressed': 'true' }, `Open (${prs.length})`), h('button', {}, 'Merged'), h('button', {}, 'Proposals')),
    h('div', { class: 'toggle sub' },
      h('button', { 'aria-pressed': String(s.view === 'project'), onclick: () => setState({ view: 'project', focus: '' }) }, 'By project'),
      h('button', { 'aria-pressed': String(s.view === 'all'), onclick: () => setState({ view: 'all', focus: '' }) }, 'All'))
  )

  const body = h('div', { class: 'body' })
  app.append(body)
  const key = h('p', { class: 'debug' }, `scroll place: mr-groups=${placeValue({ grouping: s.view, focus: s.focus || null })} · history item: ${historyItem({ grouping: s.view, focus: s.focus || null }) ?? '(the list)'}`)

  if (s.view === 'all') {
    const all = allView(prs, { sort: s.sortall === '1' })
    body.append(h('p', { class: 'lede' }, `${prs.length} open PRs, every project in one list${s.sortall === '1' ? ', in the new order' : ', as today'}.`))
    for (const pr of all) {
      const g = groups.find((x) => x.prs.some((p) => p.key === pr.key))
      body.append(card(pr, namesById(g?.id)))
    }
    body.append(key)
    return
  }

  if (focus) {
    body.append(
      h('button', { class: 'back', onclick: () => setState({ focus: '' }) }, '‹ All projects'),
      h('div', { class: 'group-head solo' }, h('span', { class: 'gname' }, focus.name), h('span', { class: 'count' }, String(focus.count)), h('span', { class: 'summary' }, needsYouSummary(focus.prs))),
      ...list(focus.prs, () => namesById(focus.id), repoOf(focus.id)), key)
    return
  }

  const needs = groups.reduce((n, g) => n + g.needsYou, 0)
  body.append(h('p', { class: 'lede' }, `${prs.length} open PRs in ${groups.filter((g) => g.count).length} projects · ${needs} need you`))
  for (const g of groups) {
    const shut = isCollapsed(g, saved, opts)
    const toggle = () => { if (!g.count) return; saved = toggleCollapsed(saved, g, opts); render() }
    const head = h('div', { class: `group-head ${g.count ? '' : 'empty'} ${g.needsYou ? 'urgent' : ''}` },
      h('button', { class: 'chev', onclick: toggle, 'aria-expanded': String(!shut), disabled: !g.count }, shut ? '▸' : '▾'),
      h('span', { class: 'gname', onclick: () => (s.tap === 'focus' && g.count ? setState({ focus: g.id }) : toggle()) }, g.name),
      h('span', { class: 'count' }, String(g.count)),
      g.needsYou ? h('span', { class: 'needs' }, `${g.needsYou} need${g.needsYou === 1 ? 's' : ''} you`) : null,
      h('span', { class: 'summary' }, needsYouSummary(g.prs)))
    body.append(h('section', { class: `group ${g.id === OTHER ? 'other' : ''}` }, head, shut ? null : h('div', { class: 'group-body' }, ...list(g.prs, () => namesById(g.id), repoOf(g.id)))))
  }
  body.append(key)
}

// The controls: one per decision, so the options can be compared side by side.
function controls() {
  const s = state()
  const row = (label, k, options) => h('label', {}, label, ' ', h('select', { onchange: (e) => setState({ [k]: e.target.value }) },
    ...options.map(([v, t]) => h('option', { value: v, selected: s[k] === v }, t))))
  const c = document.getElementById('controls')
  c.replaceChildren(
    h('strong', {}, 'Prototype'), ` · live data from ${new Date(snap.takenAt).toLocaleString()}`,
    row('Empty projects', 'empty', [['hide', 'hidden'], ['show', 'shown collapsed']]),
    row('Starts collapsed', 'collapse', [['quiet', 'nothing for you'], ['big', 'over 8 MRs'], ['open', 'none']]),
    row('Tap a project name', 'tap', [['collapse', 'collapses it'], ['focus', 'opens it alone']]),
    row('Names', 'names', [['friendly', 'friendly (Seal Speak)'], ['catalog', 'catalog (clarity-captions)']]),
    row('All is', 'sortall', [['0', 'today’s order'], ['1', 'the new order']]),
    row('Edge-case examples', 'examples', [['0', 'off'], ['1', 'on']]))
}

window.addEventListener('hashchange', () => { saved = {}; controls(); render() })
controls()
render()
