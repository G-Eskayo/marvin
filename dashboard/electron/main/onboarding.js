import { readFileSync, existsSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

const ONBOARDING_DIR = path.join(homedir(), '.claude', 'onboarding')

export function readOnboardingPlans(boards) {
  const plans = []
  if (!boards) return plans

  for (const board of boards) {
    const repo = board.repo
    const repoName = repo.split('/')[1]
    const planPath = path.join(ONBOARDING_DIR, `${repoName}.json`)

    if (!existsSync(planPath)) {
      plans.push({
        repo,
        generated_at: null,
        pieces: null,
        status: 'not_planned_yet'
      })
      continue
    }

    try {
      const content = readFileSync(planPath, 'utf-8')
      const data = JSON.parse(content)
      plans.push({
        repo,
        generated_at: data.generated_at,
        pieces: data.pieces,
        status: 'planned'
      })
    } catch {
      plans.push({
        repo,
        generated_at: null,
        pieces: null,
        status: 'read_error'
      })
    }
  }

  return plans
}
