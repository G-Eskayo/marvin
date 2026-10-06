import { readdirSync, readFileSync, existsSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

const ONBOARDING_DIR = path.join(homedir(), '.claude', 'onboarding')

export function readOnboardingPlans() {
  if (!existsSync(ONBOARDING_DIR)) return []
  try {
    const files = readdirSync(ONBOARDING_DIR).filter((n) => n.endsWith('.json'))
    const plans = []
    for (const file of files) {
      try {
        const content = readFileSync(path.join(ONBOARDING_DIR, file), 'utf-8')
        plans.push(JSON.parse(content))
      } catch {
        // Skip unparseable files defensively
      }
    }
    return plans
  } catch {
    return []
  }
}
