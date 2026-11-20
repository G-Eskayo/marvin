/**
 * pipeline_health.js — classify the ticket-pipeline job's health for the Workshop tab.
 * Given working.items (the list of running jobs), flags the ticket-pipeline job
 * as amber past 15 minutes and returns its current step/detail.
 */

export const PIPELINE_AMBER_THRESHOLD_MS = 15 * 60 * 1000;

/**
 * Classify the pipeline health based on working.items.
 * @param {Array} items - Array of working job items from window.api.working.now()
 * @param {number} now - Current time in milliseconds (default: Date.now())
 * @returns {Object|null} If the pipeline is amber: {amber: true, step: string, detail: string}
 *                        If not: null
 */
export function classifyPipelineHealth(items, now = Date.now()) {
  if (!Array.isArray(items)) return null

  const pipeline = items.find((item) => item?.job === 'ticket-pipeline')
  if (!pipeline) return null

  const startedAt = pipeline.startedAt
  if (typeof startedAt !== 'number') return null

  const elapsed = now - startedAt
  if (elapsed < PIPELINE_AMBER_THRESHOLD_MS) return null

  // The job is amber — return step/detail
  const step = pipeline.current?.step || 'unknown'
  const detail = pipeline.current?.detail || ''

  return {
    amber: true,
    step,
    detail,
    elapsed
  }
}
