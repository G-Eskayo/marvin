import { readdirSync, readFileSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

const ONBOARDING_DIR = path.join(homedir(), '.claude', 'onboarding')

function parseState(state) {
  if (state === 'ok') return 'ok'
  if (state === 'missing') return 'missing'
  if (state === 'needs-human') return 'needs-human'
  return 'unknown'
}

function stateToSeverity(state) {
  if (state === 'ok') return 'green'
  if (state === 'needs-human') return 'yellow'
  if (state === 'missing') return 'red'
  return 'yellow'
}

export function buildReadiness({ files }) {
  const projects = []
  for (const file of files) {
    try {
      const content = JSON.parse(file.content)
      const repo = content.repo
      const generatedAt = content.generated_at
      const error = content.error

      if (error) {
        projects.push({
          repo,
          name: repo.split('/')[1] || repo,
          generatedAt,
          error,
          pieces: {},
          worstState: 'error'
        })
        continue
      }

      const plan = content.plan || {}
      const pieces = {}
      let worstSeverity = 2 // ok=2, missing=1, needs-human=0
      let worstState = 'ok'

      for (const [key, piece] of Object.entries(plan)) {
        if (typeof piece === 'object' && piece !== null && piece.state) {
          const state = parseState(piece.state)
          const reason = piece.reason || ''
          pieces[key] = { state, reason }

          // Track worst state: error > needs-human > missing > ok
          const severity = { 'needs-human': 0, 'missing': 1, 'ok': 2 }[state] ?? 2
          if (severity < worstSeverity) {
            worstSeverity = severity
            worstState = state
          }
        }
      }

      projects.push({
        repo,
        name: repo.split('/')[1] || repo,
        generatedAt,
        pieces,
        worstState
      })
    } catch (e) {
      // Malformed file: skip it
    }
  }

  // Sort worst-state-first (missing > needs-human > ok)
  const stateOrder = { 'error': 0, 'missing': 1, 'needs-human': 2, 'ok': 3 }
  return projects.sort((a, b) => {
    const aOrder = stateOrder[a.worstState] ?? 4
    const bOrder = stateOrder[b.worstState] ?? 4
    if (aOrder !== bOrder) return aOrder - bOrder
    return a.name.localeCompare(b.name)
  })
}

export function readProjectReadiness({ dir = ONBOARDING_DIR } = {}) {
  const files = []
  try {
    const entries = readdirSync(dir)
    for (const entry of entries) {
      if (!entry.endsWith('.json')) continue
      try {
        const filePath = path.join(dir, entry)
        const content = readFileSync(filePath, 'utf-8')
        files.push({ name: entry, content })
      } catch {
        // unreadable file: skip it
      }
    }
  } catch {
    // directory doesn't exist yet
  }
  return buildReadiness({ files })
}
