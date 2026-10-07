// What is running where, against each machine's slots (ADR 0052). `running` is lib/ticket_queue.py's list (one row per
// claimed ticket, with its machine); `settings` is config/dispatch.json. The limit mirrors lib/dispatch_concurrency.py:
// one per machine unless parallel is on, then the smaller of the machine's slots and the total.
export function effectiveLimit(settings, machine) {
  if (!settings?.parallel) return 1
  return Math.max(1, Math.min(settings.machine_slots?.[machine] ?? 1, settings.max_total))
}

// The most that can run at once across every machine; a total above this is capped by the machines.
export function capacity(settings) {
  const machines = Object.keys(settings?.machine_slots || {})
  if (!settings?.parallel) return machines.length || 1
  const sum = machines.reduce((n, m) => n + effectiveLimit(settings, m), 0)
  return Math.max(1, Math.min(sum, settings.max_total))
}

export function describeMachines({ running = [], settings }) {
  const names = [...new Set([...Object.keys(settings?.machine_slots || {}), ...running.map((r) => r.machine)])]
  return names.map((machine) => {
    const tickets = running.filter((r) => r.machine === machine).map((r) => `${r.project} #${r.number} ${r.title}`)
    return { machine, used: tickets.length, limit: effectiveLimit(settings, machine), tickets }
  })
}
