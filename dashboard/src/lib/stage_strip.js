import { TERMINAL_STAGE_ORDER, STAGE_LABEL } from '../../src/lib/stage_names.js'

export { TERMINAL_STAGE_ORDER, STAGE_LABEL }

const STALL_THRESHOLD_MS = 60 * 60 * 1000 // 1 hour

export function deriveStageStrip(events, { isLiveNow = false, now = () => new Date() } = {}) {
  if (events.length === 0) return []

  const latestByStage = new Map()
  let mostRecentTimestamp = null
  for (const event of events) {
    if (!TERMINAL_STAGE_ORDER.includes(event.stage)) continue
    const existing = latestByStage.get(event.stage)
    if (!existing || new Date(event.timestamp) > new Date(existing.timestamp)) {
      latestByStage.set(event.stage, event)
    }
    const eventTime = new Date(event.timestamp)
    if (!mostRecentTimestamp || eventTime > mostRecentTimestamp) {
      mostRecentTimestamp = eventTime
    }
  }

  const nowTime = now()
  return TERMINAL_STAGE_ORDER
    .filter((stage) => latestByStage.has(stage))
    .map((stage) => {
      const event = latestByStage.get(stage)
      const { detail, remediation } = extractRemediation(event.detail || '')
      const needsRebase = stage === 'gate' && event.status === 'failed' && /^REBASE_CONFLICT\b/.test(detail)
      const eventTime = new Date(event.timestamp)
      const ageMs = nowTime - eventTime
      const liveStatus = isLiveNow && eventTime.getTime() === mostRecentTimestamp.getTime() && event.status === 'started'
        ? ageMs > STALL_THRESHOLD_MS ? 'stalled' : 'running'
        : null

      return {
        stage: event.stage,
        status: event.status,
        detail,
        remediation,
        needsRebase,
        when: formatTime(event.timestamp),
        money: formatMoney(event.cost_usd),
        timestamp: event.timestamp,
        machine: event.machine || 'unknown',
        liveStatus,
        title: event.title
      }
    })
}

function extractRemediation(detail) {
  const lines = detail.split('\n')
  const remediationIdx = lines.findIndex((l) => l.trim().startsWith('Remediation:'))
  if (remediationIdx < 0) {
    return { detail, remediation: null }
  }
  const remediationLine = lines[remediationIdx].trim()
  const remediation = remediationLine.slice('Remediation:'.length).trim() + (lines.length > remediationIdx + 1 ? '\n' + lines.slice(remediationIdx + 1).join('\n').trim() : '')
  const mainDetail = lines.slice(0, remediationIdx).join('\n').trim()
  return { detail: mainDetail, remediation }
}

export function formatTime(iso) {
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

export function formatMoney(usd) {
  if (!usd) return '$0.00'
  return `$${usd.toFixed(usd < 0.01 ? 4 : 2)}`
}
