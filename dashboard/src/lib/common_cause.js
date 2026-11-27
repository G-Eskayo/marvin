// Fold repeating refused rows with the same root cause into a single incident row.
// Pure function: rows → rows with folded incidents, preserving non-refused rows in order.

export const ROOT_BY_CODE = {
  MAIN_RED: 'MAIN_RED',
  RATE_LIMITED: 'GITHUB',
  GITHUB_OUTAGE: 'GITHUB',
  MEMORY_PRESSURE: 'MEMORY_PRESSURE',
  CI_PENDING: 'CI_PENDING',
  CI_FAILED: 'CI_FAILED',
  NOT_MERGEABLE: 'NOT_MERGEABLE',
}

export const ROOT_LABEL = {
  MAIN_RED: 'main is red',
  GITHUB: 'GitHub is down',
  MEMORY_PRESSURE: 'memory pressure',
  CI_PENDING: 'checks still running',
  CI_FAILED: 'tests failed',
  NOT_MERGEABLE: 'conflicts with main',
}

export function foldCommonCause(rows, { rootByCode = ROOT_BY_CODE, gapHours = 2 } = {}) {
  if (!rows || rows.length === 0) return rows

  const gapMs = gapHours * 60 * 60 * 1000

  // Extract refused rows with known codes and their original indices
  const foldableRefused = []
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i]
    if (row.kind === 'refused' && row.code && rootByCode[row.code]) {
      foldableRefused.push({ row, originalIndex: i })
    }
  }

  if (foldableRefused.length === 0) return rows

  // Sort by root, then by at (newest first). NaN dates go to end.
  foldableRefused.sort((a, b) => {
    const rootA = rootByCode[a.row.code]
    const rootB = rootByCode[b.row.code]
    if (rootA !== rootB) return rootA.localeCompare(rootB)

    const dateA = Date.parse(a.row.at)
    const dateB = Date.parse(b.row.at)

    if (Number.isNaN(dateA) && Number.isNaN(dateB)) return 0
    if (Number.isNaN(dateA)) return 1
    if (Number.isNaN(dateB)) return -1

    return dateB - dateA // newest first
  })

  // Group into incidents: same root, split on gap
  const incidents = []
  let currentRoot = null
  let currentIncident = []
  let lastValidDate = null

  for (const item of foldableRefused) {
    const root = rootByCode[item.row.code]
    const date = Date.parse(item.row.at)
    const isValidDate = !Number.isNaN(date)

    if (currentRoot !== root) {
      // New root: save current incident and start new
      if (currentIncident.length > 0) {
        incidents.push({ root: currentRoot, items: currentIncident })
      }
      currentRoot = root
      currentIncident = [item]
      lastValidDate = isValidDate ? date : null
    } else if (isValidDate && lastValidDate && (lastValidDate - date) > gapMs) {
      // Gap detected: save current incident and start new
      incidents.push({ root: currentRoot, items: currentIncident })
      currentIncident = [item]
      lastValidDate = date
    } else {
      // Same incident
      currentIncident.push(item)
      if (isValidDate && (!lastValidDate || date > lastValidDate)) {
        lastValidDate = date
      }
    }
  }

  if (currentIncident.length > 0) {
    incidents.push({ root: currentRoot, items: currentIncident })
  }

  // Build incident info: for each original index, which incident (if any)
  const indexToIncident = new Map()
  for (let i = 0; i < incidents.length; i++) {
    for (const item of incidents[i].items) {
      indexToIncident.set(item.originalIndex, i)
    }
  }

  // Process each incident: dedup by url and fold if 2+ items initially
  const incidentResults = new Map() // Map from incident index to folded row or null

  for (let i = 0; i < incidents.length; i++) {
    const incident = incidents[i]

    if (incident.items.length < 2) {
      incidentResults.set(i, null) // Single item: don't fold
      continue
    }

    // Check if any item has invalid date: don't fold if so
    let hasInvalidDate = false
    for (const item of incident.items) {
      if (!item.row.at || Number.isNaN(Date.parse(item.row.at))) {
        hasInvalidDate = true
        break
      }
    }
    if (hasInvalidDate) {
      incidentResults.set(i, null) // Invalid date: don't fold
      continue
    }

    // Dedup by url (keep latest). Missing url = keep row as-is.
    let hasInvalidUrl = false
    const byUrl = new Map()

    for (const item of incident.items) {
      if (!item.row.url) {
        hasInvalidUrl = true
        break
      }

      if (!byUrl.has(item.row.url)) {
        byUrl.set(item.row.url, item.row)
      } else {
        const existingDate = Date.parse(byUrl.get(item.row.url).at)
        const currentDate = Date.parse(item.row.at)

        // Keep item if newer (or existing is invalid and current is valid)
        if (Number.isNaN(existingDate) || (!Number.isNaN(currentDate) && currentDate > existingDate)) {
          byUrl.set(item.row.url, item.row)
        }
      }
    }

    if (hasInvalidUrl) {
      incidentResults.set(i, null) // Can't dedup: don't fold
      continue
    }

    // Reverse to get oldest-first order: byUrl stores in newest-first (insertion order from sorted incident.items)
    const items = Array.from(byUrl.values()).reverse()

    // Find latest timestamp for folded row
    const latestItem = items.reduce((latest, item) => {
      const latestDate = Date.parse(latest.at)
      const itemDate = Date.parse(item.at)
      if (Number.isNaN(latestDate) || Number.isNaN(itemDate)) {
        return !Number.isNaN(itemDate) ? item : latest
      }
      return itemDate > latestDate ? item : latest
    })

    const foldedRow = {
      kind: 'folded',
      root: incident.root,
      label: ROOT_LABEL[incident.root] || incident.root,
      at: latestItem.at,
      count: items.length,
      items,
    }

    incidentResults.set(i, foldedRow)
  }

  // Build result: iterate original rows, output folded incident at first occurrence or all rows if not folded
  const result = []
  const seenIncidents = new Set()

  for (let i = 0; i < rows.length; i++) {
    const row = rows[i]

    if (indexToIncident.has(i)) {
      // This is a foldable refused row
      const incidentIdx = indexToIncident.get(i)

      if (!seenIncidents.has(incidentIdx)) {
        // First row of this incident: output folded row if it exists
        seenIncidents.add(incidentIdx)
        const folded = incidentResults.get(incidentIdx)
        if (folded) {
          result.push(folded)
        }
      }

      // If incident was folded, skip all rows. If not folded, output each row.
      if (!incidentResults.get(incidentIdx)) {
        result.push(row)
      }
    } else {
      // Not a foldable refused row: keep as-is
      result.push(row)
    }
  }

  return result
}
