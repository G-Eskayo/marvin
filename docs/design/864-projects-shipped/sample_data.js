// Sample data for the #864 mock-up, shaped like the real sources: the catalog's one name per project (#935's
// project_names.js), the profiles' goals and signals (instance/config/projects/<repo>.json), next_step's sections and
// verbs (Now, #1030), mr_groups.js's tiers, and MR Review ▸ Merged's history rows. Titles are real-looking work from
// the public boards; nothing private. Times are relative to the page's "now".
(function (root) {
  'use strict'
  const MIN = 60000
  const H = 60 * MIN
  const D = 24 * H

  const projects = [
    {
      id: 'marvin', name: 'MARVIN', repo: 'marvin', status: 'active', hasBoard: true, mergedWeek: 21,
      goal: 'Work gets done without you chasing it, cheaply and within budget before the plan ends; it keeps working without the paid subscription; and it acts as your partner that improves your day.',
      signals: [{ name: 'merged PRs per week', better: 'up' }, { name: 'cost per merged PR', better: 'down' }, { name: 'decisions waiting on you', better: 'down' }, { name: 'local share of work', better: 'up' }],
      opened30: [3, 5, 7, 8, 10, 13, 15, 18, 22, 24, 27, 31, 33, 36, 40, 44, 47, 49, 53, 56, 60, 63, 66, 70, 73, 77, 80, 84, 86, 90],
      shipped30: [2, 4, 6, 8, 9, 12, 14, 16, 19, 22, 24, 27, 30, 33, 35, 38, 41, 44, 46, 50, 53, 55, 58, 61, 64, 68, 70, 73, 76, 79],
      items: [
        { key: 'm1', type: 'pr', number: 1049, ticket: 1047, title: 'Main red fix: checks of outside state are named in Health, not main red', section: 'yours', tier: 'needs-you', verb: 'Approve', lane: 'Merge gate', stage: 4, priority: 'p1', waitingMin: 40, meta: ['checks passed'] },
        { key: 'm2', type: 'pr', number: 1048, ticket: 1046, title: 'Main red fix: the marvin show test no longer hard-codes a reserved folder', section: 'yours', tier: 'needs-you', verb: 'Approve', lane: 'Merge gate', stage: 4, priority: 'p1', waitingMin: 35, meta: ['checks passed'] },
        { key: 'm3', type: 'pr', number: 1041, ticket: 872, title: 'Mock-up: plan usage and one Auto throttle switch with guardrails', section: 'yours', tier: 'needs-you', verb: 'Answer 3 decisions', lane: 'Dashboard', stage: 2, priority: 'p2', waitingMin: 150, meta: ['mock-up'] },
        { key: 'm4', type: 'ticket', number: 1015, title: 'Ticket links: a ticket names the tickets it builds on', section: 'yours', verb: 'Give info', lane: 'Pipeline', stage: 0, priority: 'p3', waitingMin: 300, meta: ['needs-info'] },
        { key: 'm5', type: 'pr', number: 981, ticket: 951, title: 'Box builds: Linux-safe tickets go to a fresh VM on the spare box', section: 'stuck', tier: 'stuck', verb: 'No movement', lane: 'Box builds', stage: 3, priority: 'p2', meta: ['held on the Mini', 'no movement since 09:40'], right: 'Restart ▸' },
        { key: 'm6', type: 'ticket', number: 1028, title: 'Topic handoffs: each handoff named by project and topic', section: 'marvin', verb: 'Building', lane: 'Pipeline', stage: 3, liveEvent: true, meta: ['Mac mini', 'helper tab', '18 min'], right: 'build' },
        { key: 'm7', type: 'pr', number: 977, ticket: 974, title: 'Accounts: live checks, expiry warnings and renewal for every credential', section: 'marvin', tier: 'running', verb: 'Checks running', lane: 'Vitals', stage: 4, liveEvent: true, meta: ['GitHub checks 4 of 6'], right: 'review' },
        { key: 'm8', type: 'pr', number: 935, ticket: 848, title: 'MR Review opens By project, with one set of project names everywhere', section: 'marvin', tier: 'stuck', verb: 'Being fixed', lane: 'Dashboard', stage: 4, liveEvent: false, meta: ['conflicts with main', 'MacBook', '22 min'], right: 'build' },
        { key: 'm9', type: 'ticket', number: 937, title: 'Vitals: one card per budget, each with its soft and hard line', section: 'next', verb: 'Next', lane: 'Vitals', stage: 0, priority: 'p1', meta: ['Mac mini'], right: 'ready' },
        { key: 'm10', type: 'ticket', number: 1003, title: 'Disk first aid: clear build caches before a build starts', section: 'next', verb: 'Next', lane: 'Pipeline', stage: 0, priority: 'p2', meta: [], right: 'ready' },
        { key: 'm11', type: 'pr', number: 1039, ticket: 1038, title: 'Profile parity: one facts file, one check, a Health row on drift', section: 'waiting', tier: 'draft', isDraft: true, verb: 'Draft', stage: 3, meta: ['draft'] }
      ]
    },
    {
      id: 'clarity-captions', name: 'Seal Speak', repo: 'clarity-captions', status: 'active', hasBoard: true, mergedWeek: 9,
      goal: 'Any hard-of-hearing person can rely on Seal Speak: iPhone first, then Android.',
      signals: [{ name: 'testers and users', better: 'up' }, { name: 'crash-free days', better: 'up' }, { name: 'App Store rating', better: 'up' }],
      opened30: [1, 2, 4, 6, 9, 11, 12, 14, 17, 19, 20, 22, 25, 27, 30, 32, 33, 35, 36, 38, 40, 41, 43, 44, 46, 47, 48, 50, 51, 53],
      shipped30: [0, 1, 3, 4, 6, 8, 9, 11, 12, 14, 16, 17, 19, 21, 23, 25, 27, 29, 30, 32, 34, 36, 37, 38, 40, 41, 42, 44, 45, 46],
      items: [
        { key: 's1', type: 'pr', number: 255, ticket: 246, title: 'Mock-up: a cleaner translated caption, three options on iPhone, iPad and Mac', section: 'yours', tier: 'needs-you', verb: 'Approve the look', lane: 'Translation', stage: 2, priority: 'p1', waitingMin: 380, meta: ['mock-up'] },
        { key: 's2', type: 'pr', number: 256, ticket: 252, title: 'From and Into: same language allowed, a swap button', section: 'yours', tier: 'needs-you', verb: 'Answer 2 decisions', lane: 'Translation', stage: 2, priority: 'p2', waitingMin: 200, meta: [] },
        { key: 's3', type: 'pr', number: 254, ticket: 247, title: 'Spike: the in-ear voice matched to each speaker\'s pitch and pace', section: 'marvin', tier: 'running', verb: 'Checks running', lane: 'Ear translation', stage: 4, liveEvent: true, meta: ['GitHub checks 2 of 3'], right: 'review' },
        { key: 's4', type: 'ticket', number: 248, title: 'Hebrew pack: a first measured model, smallest size without losing quality', section: 'marvin', verb: 'Building', lane: 'Languages', stage: 3, liveEvent: true, meta: ['MacBook', 'helper tab', '41 min'], right: 'build' },
        { key: 's5', type: 'pr', number: 231, ticket: 213, title: 'Mac Live Translation on calls and in the room: mock-ups and the core rules', section: 'waiting', tier: 'draft', isDraft: true, verb: 'Draft', lane: 'Mac', stage: 2, meta: ['draft'] }
      ]
    },
    {
      id: 'portfolio-website-updater', name: 'Portfolio', repo: 'portfolio-website-updater', status: 'active', hasBoard: true, mergedWeek: 0, due: 'Nov 14',
      goal: 'Recruiters and high-end clients see you as an AI/ML/security professional, and it lands interviews.',
      signals: [{ name: 'recruiter contacts', better: 'up' }, { name: 'project pages with real proof', better: 'up' }],
      opened30: [0, 0, 1, 1, 2, 2, 3, 3, 3, 4, 4, 5, 5, 6, 6, 6, 7, 7, 8, 8, 8, 9, 9, 10, 10, 10, 11, 11, 11, 12],
      shipped30: [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 5, 5, 5, 6, 6, 6, 7, 7, 7, 7, 8, 8, 8, 8],
      items: [
        { key: 'p1', type: 'pr', number: 11, ticket: 9, title: 'Brand redesign into WordPress: all 27 pages from the mock-ups', section: 'yours', tier: 'needs-you', verb: 'Approve', lane: 'Redesign', stage: 4, priority: 'p2', waitingMin: 2 * 24 * 60, meta: ['checks passed'] },
        { key: 'p2', type: 'pr', number: 8, ticket: 7, title: 'Refresh the MARVIN and Seal Speak pages: re-measured numbers, new charts', section: 'waiting', tier: 'waiting', verb: 'Waiting on #11', lane: 'Pages', stage: 4, meta: ['stacked on PR #11'] }
      ]
    },
    {
      id: 'marvin-voice', name: 'MARVIN Voice', repo: 'marvin-voice', status: 'active', hasBoard: true, mergedWeek: 2, goal: null, signals: [],
      opened30: [0, 0, 0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5, 5, 5, 6, 6, 6, 6, 7, 7, 7, 7, 8],
      shipped30: [0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 6, 6, 6, 6],
      items: [
        { key: 'v1', type: 'ticket', number: 9, title: 'Dictation: push to talk in any app, captions from the shared engine', section: 'marvin', verb: 'Building', stage: 3, liveEvent: true, meta: ['MacBook', '6 min'], right: 'build' }
      ]
    },
    {
      id: 'thermal-forge', name: 'thermal-forge', repo: 'thermal-forge', status: 'active', hasBoard: true, mergedWeek: 0,
      goal: 'Give an everyday household computer a supercomputer-style cooling system, designing the PC and its cooling together.',
      signals: [{ name: 'heat-path tools tested against known results', better: 'up' }],
      opened30: [0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5, 5],
      shipped30: [0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3],
      items: [
        { key: 't1', type: 'ticket', number: 14, title: 'Heat-path solver checked against a textbook fin result', section: 'next', verb: 'Next', lane: 'Heat path', stage: 0, priority: 'p2', meta: [], right: 'ready' }
      ]
    },
    {
      id: 'finance-os', name: 'Finance OS', repo: 'finance-os', status: 'active', hasBoard: true, mergedWeek: 0, held: 1,
      goal: 'Money on autopilot: you always know where money goes and the budget runs itself.',
      signals: [{ name: 'transactions auto-sorted', better: 'up' }, { name: 'months on budget', better: 'up' }],
      opened30: [2, 2, 2, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5],
      shipped30: [1, 1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4],
      items: [
        { key: 'f1', type: 'ticket', number: 41, title: 'Categories learn from each correction you make', section: 'waiting', verb: 'Held', stage: 0, meta: ['hold'] }
      ]
    },
    {
      id: 'marvin-mobile', name: 'MARVIN Mobile', repo: 'marvin-mobile', status: 'active', hasBoard: true, mergedWeek: 0,
      goal: 'MARVIN in your pocket: everything you do in the dashboard, from your phone.',
      signals: [{ name: 'approvals done from the phone', better: 'up' }],
      opened30: Array(30).fill(4), shipped30: Array(30).fill(3), items: []
    },
    {
      id: 'resume-tailor', name: 'Resume tailor', repo: 'resume-tailor', status: 'active', hasBoard: false, mergedWeek: 0,
      goal: 'Every application gets a resume fitted honestly to the posting, so more applications turn into interviews.',
      signals: [{ name: 'interview rate per application', better: 'up' }],
      opened30: Array(30).fill(0), shipped30: Array(30).fill(0), items: []
    },
    {
      id: 'other', name: 'Other', why: 'two project labels (project:marvin and project:clarity-captions): fix the labels and it moves to its project', mergedWeek: 0,
      items: [
        { key: 'o1', type: 'pr', number: 1020, title: 'MARVIN website, phase 1: landing, why, waitlist, docs hub and feature pages', section: 'yours', tier: 'needs-you', verb: 'Approve', stage: 4, priority: 'p3', waitingMin: 900, meta: ['checks passed'] }
      ]
    },
    { id: 'paper-dive', name: 'paper-dive', repo: 'paper-dive', status: 'parked', hasBoard: true, goal: null, items: [] },
    { id: 'nourished', name: 'Nourished', repo: 'nourished', status: 'parked', hasBoard: true, goal: null, items: [] },
    { id: 'killer-sudoku', name: 'Killer Sudoku', repo: 'killer-sudoku', status: 'done', hasBoard: true, goal: null, items: [] },
    { id: 'mitre-technique-prediction', name: 'mitre-technique-prediction', repo: 'mitre-technique-prediction', status: 'archived', hasBoard: true, goal: null, items: [] }
  ]

  // The ship steps ADR 0080 I4 names (each project profile, once I4 lands). Today no profile has one.
  const shipsI4 = {
    marvin: { kind: 'macs', targets: ['MacBook', 'Mini'] },
    'clarity-captions': { kind: 'testflight' },
    'portfolio-website-updater': { kind: 'pages', where: 'the live site' }
  }

  // MR Review ▸ Merged's rows (window.api.mr.history), plus `live` for the ship step. `ago` is minutes before now.
  const history = [
    { kind: 'merged', number: 1042, project: 'marvin', title: 'Plan usage: record the Claude plan\'s 5-hour and weekly meters, summarise across Macs', by: 'you', ago: 70, live: { pulled: ['MacBook'] }, shipping: true },
    { kind: 'merged', number: 1036, project: 'marvin', title: 'Bench Run 31: where MARVIN\'s extra cost per task goes, and what holds up', by: 'auto', ago: 160, live: { pulled: ['MacBook', 'Mini'] } },
    { kind: 'merged', number: 1029, project: 'marvin', title: 'marvin show: open what a session is talking about in its project\'s MARVIN window', by: 'you', ago: 165, live: { pulled: ['MacBook', 'Mini'] } },
    { kind: 'merged', number: 1011, project: 'marvin', title: 'A PR names its ticket as Closes or Part of; bin/gh refuses PRs that name none', by: 'you', ago: 166, live: { pulled: ['MacBook', 'Mini'] } },
    { kind: 'refused', number: 1032, project: 'marvin', title: 'marvin show, slice 2: history strip and opening on the Mac in use', reason: 'decisions not answered yet', ago: 300 },
    { kind: 'merged', number: 1025, project: 'marvin', title: 'Public docs name machines generically, not by hostname', by: 'auto', ago: 620, live: { pulled: ['MacBook', 'Mini'] } },
    { kind: 'merged', number: 1030, project: 'marvin', title: 'Workshop tab: the Now view (Stuck, Your move, MARVIN is on it, Up next)', by: 'you', ago: 621, live: { pulled: ['MacBook', 'Mini'] } },
    { kind: 'merged', number: 1023, project: 'marvin', title: 'Memory search warns when its keyword half can\'t run', by: 'auto', ago: 24 * 60 + 200, live: { pulled: ['MacBook', 'Mini'] } },
    { kind: 'merged', number: 1010, project: 'marvin', title: 'MR Review: a queued merge shows its merge pipeline on every Mac', by: 'you', ago: 24 * 60 + 260, live: { pulled: ['MacBook', 'Mini'] }, revertedBy: 1012 },
    { kind: 'merged', number: 1012, project: 'marvin', title: 'Revert the merge-pipeline strip until the Mini reads it too', by: 'you', ago: 24 * 60 + 240, live: { pulled: ['MacBook', 'Mini'] } },
    { kind: 'merged', number: 250, project: 'clarity-captions', title: 'Face to face: never trapped, never silent, set up in Settings first', by: 'you', ago: 4 * 24 * 60 + 100, live: { state: 'live', build: '1.1.0 (10)' } },
    { kind: 'merged', number: 241, project: 'clarity-captions', title: 'Parakeet for every language both engines caption: six languages routed', by: 'you', ago: 4 * 24 * 60 + 500, live: { state: 'live', build: '1.1.0 (10)' } },
    { kind: 'merged', number: 238, project: 'clarity-captions', title: 'Live Translation in your ear: turn it on in Settings, spoken into any headphones', by: 'you', ago: 4 * 24 * 60 + 450, live: { state: 'live', build: '1.1.0 (10)' } },
    { kind: 'merged', number: 239, project: 'clarity-captions', title: 'Mac app builds again: language rows, Mac build in CI', by: 'auto', ago: 4 * 24 * 60 + 510, live: { state: 'failed', reason: 'Mac upload rejected: missing export option' } },
    { kind: 'merged', number: 6, project: 'marvin-mobile', title: 'App icon: celestial-navigation M on pure black', by: 'you', ago: 7 * 24 * 60 + 60, live: {} },
    { kind: 'merged', number: 7, project: 'portfolio-website-updater', title: 'Seal Speak page: the rename, with re-measured numbers', by: 'you', ago: 8 * 24 * 60 + 60, live: { state: 'live' } }
  ]
  // A few more days, so the bars and the pages have something to show.
  const fill = [[2, 6], [3, 4], [5, 3], [6, 5], [9, 2], [10, 4], [11, 3], [12, 6], [13, 1]]
  for (const [day, n] of fill) {
    for (let i = 0; i < n; i++) history.push({ kind: 'merged', number: 900 - day * 10 - i, project: i % 3 ? 'marvin' : 'clarity-captions', title: i % 3 ? 'Health check reads its own reason, fix and age' : 'Captions keep their place when the app comes back', by: i % 2 ? 'auto' : 'you', ago: day * 24 * 60 + 120 + i * 40, live: i % 3 ? { pulled: ['MacBook', 'Mini'] } : { state: 'live', build: '1.1.0 (11)' } })
  }
  // The merge the "A merge arrives" button plays in (it was the first "Approve" in Projects).
  const arriving = { kind: 'merged', number: 1049, project: 'marvin', title: 'Main red fix: checks of outside state are named in Health, not main red', by: 'you', ago: 0, live: { pulled: [] }, shipping: true }

  const proposals = [
    { title: 'Run cheap work on the spare box, keep the plan for the hard parts', star: 'Minimise resources', size: 'L', problem: 'Every build runs on the paid plan, even small ones a local model handles.', fix: 'Send Linux-safe, low-risk tickets to the spare box first; the plan only for what needs it.', why: 'More gets done before the plan ends, and it keeps working without it.' }
  ]

  root.Sample864 = { projects, shipsI4, history, arriving, proposals, MIN, H, D }
})(typeof globalThis !== 'undefined' ? globalThis : window)
