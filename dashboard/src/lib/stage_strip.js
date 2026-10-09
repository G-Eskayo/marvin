// Derives pipeline stage segments from a timeline of stage-log events,
// including liveness detection (started vs stalled), status summary,
// and the full per-stage event history for drill-in views. Stateless
// pure function: feed in the raw events array and liveness context,
// get back the segments to render. No storage, no side effects.

const VALID_STAGES_ORDERED = [
  'claimed',
  'planning',
  'executing',
  'verifying',
  'gate',
  'mutation',
  'merging',
  'rebuilding',
  'done'
]

const STAGE_LABEL = {
  claimed: 'Claimed',
  planning: 'Planning',
  executing: 'Executing',
  verifying: 'Verifying',
  gate: 'Gate',
  mutation: 'Mutation',
  merging: 'Merging',
  rebuilding: 'Rebuilding',
  done: 'Done',
  rebase: 'Rebase'
}

// Parse "refused CODE: message" or "CODE: message" detail strings.
// Returns { code, message } or { code: 'UNKNOWN', message: detail }.
function parseDetail(detail) {
  if (!detail || typeof detail !== 'string') return { code: 'UNKNOWN', message: '' }
  const refusedMatch = detail.match(/^refused\s+(\w+):\s*(.*)$/)
  if (refusedMatch) return { code: refusedMatch[1], message: refusedMatch[2] }
  const codeMatch = detail.match(/^(\w+):\s*(.*)$/)
  if (codeMatch) return { code: codeMatch[1], message: codeMatch[2] }
  return { code: 'UNKNOWN', message: detail }
}

// Get remediation text for a failure code. Only OUT_OF_ORDER has a distinct
// label (relabeled to "Order check"); all others get generic remediation.
function getRemediation(code) {
  if (code === 'OUT_OF_ORDER') return null
  if (code === 'REBASE_CONFLICT') return 'Rebase onto main failed due to merge conflict. Fix conflicts and push updates.'
  if (code.startsWith('GATE_')) return 'The merge gate failed. Check the PR logs for details.'
  return ''
}

export function deriveSegments(
  events,
  {
    rebase = null,
    isLiveNow = false,
    now = Date.now(),
    stallMinutes = 30
  } = {}
) {
  if (!events || !Array.isArray(events)) {
    events = []
  }

  const segments = []
  const byStage = new Map()

  // Group events by stage, filter out garbage/unknown stages
  for (const event of events) {
    if (!event || !event.stage || !VALID_STAGES_ORDERED.includes(event.stage)) continue
    if (!byStage.has(event.stage)) byStage.set(event.stage, [])
    byStage.get(event.stage).push(event)
  }

  if (byStage.size === 0 && !rebase) return []

  // Find the first and furthest stages with any events
  let firstStageIdx = VALID_STAGES_ORDERED.length
  let furthestStageIdx = -1
  for (const [stage] of byStage) {
    const idx = VALID_STAGES_ORDERED.indexOf(stage)
    if (idx < firstStageIdx) firstStageIdx = idx
    if (idx > furthestStageIdx) furthestStageIdx = idx
  }

  if (furthestStageIdx < 0) return []
  const startIdx = firstStageIdx >= 0 ? firstStageIdx : 0

  // Terminal stages: don't trail pending after these
  const TERMINAL_STAGES = new Set(['done'])
  const furthestStage = VALID_STAGES_ORDERED[furthestStageIdx]
  const isTerminal = TERMINAL_STAGES.has(furthestStage)

  // First pass: emit only stages that have events
  for (let i = startIdx; i <= furthestStageIdx; i++) {
    const stage = VALID_STAGES_ORDERED[i]
    const stageEvents = byStage.get(stage)
    if (!stageEvents || stageEvents.length === 0) continue

    let status = stageEvents[stageEvents.length - 1].status
    const latest = stageEvents[stageEvents.length - 1]
    let message = ''
    let remediation = ''
    let label = STAGE_LABEL[stage]

    // Liveness detection: override "started" based on dispatch state and elapsed time
    if (status === 'started' && !isLiveNow) {
      status = 'stalled'
    } else if (status === 'started' && isLiveNow) {
      try {
        const eventTime = new Date(latest.timestamp).getTime()
        const elapsedMs = now - eventTime
        const stallMs = stallMinutes * 60 * 1000
        if (elapsedMs > stallMs) {
          status = 'stalled'
        }
      } catch {
        status = 'stalled'
      }
    }

    // Parse detail for failed stages to extract code and message
    if (latest.status === 'failed' && latest.detail) {
      const parsed = parseDetail(latest.detail)
      message = parsed.message
      if (parsed.code === 'OUT_OF_ORDER') {
        label = 'Order check'
      }
      remediation = getRemediation(parsed.code)
    }

    segments.push({
      stage,
      status,
      label,
      message: message || '',
      remediation: remediation || '',
      machine: latest.machine,
      cost_usd: latest.cost_usd,
      timestamp: latest.timestamp,
      events: stageEvents
    })

    if (TERMINAL_STAGES.has(stage)) break
  }

  // Second pass: if not at a terminal stage, add pending stages up to 'merging'
  if (!isTerminal && furthestStageIdx < VALID_STAGES_ORDERED.indexOf('done')) {
    const mergingIdx = VALID_STAGES_ORDERED.indexOf('merging')
    for (let i = furthestStageIdx + 1; i <= mergingIdx; i++) {
      const stage = VALID_STAGES_ORDERED[i]
      segments.push({
        stage,
        status: 'pending',
        label: STAGE_LABEL[stage],
        message: '',
        remediation: '',
        machine: undefined,
        cost_usd: undefined,
        timestamp: undefined,
        events: []
      })
    }
  }

  // Add rebase segment if present
  if (rebase) {
    if (rebase.status === 'conflict') {
      segments.unshift({
        stage: 'rebase',
        status: 'failed',
        label: STAGE_LABEL.rebase,
        message: 'Rebase conflict',
        remediation: 'Resolve conflicts and push updates to the PR branch.',
        machine: undefined,
        cost_usd: undefined,
        timestamp: undefined,
        events: []
      })
    }
  }

  return segments
}
