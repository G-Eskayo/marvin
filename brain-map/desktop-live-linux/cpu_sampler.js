'use strict'
const { app } = require('electron')
const { homedir } = require('os')
const { join, dirname } = require('path')
const { appendFileSync, mkdirSync, statSync, readFileSync, writeFileSync } = require('fs')

const LOG_DIR = join(homedir(), '.claude', 'logs')
const LOG_FILE = join(LOG_DIR, 'cpu-sampler.log')
const MAX_BYTES = 50 * 1024 * 1024
const KEEP_BYTES = 40 * 1024 * 1024  // keep at least 40 MB when trimming

function trimLog(logFile) {
  try {
    const stats = statSync(logFile)
    if (stats.size > MAX_BYTES) {
      const content = readFileSync(logFile, 'utf-8')
      const lines = content.split('\n')
      // Find cutoff point: keep lines until we're under KEEP_BYTES
      let kept = 0
      let startIdx = 0
      for (let i = lines.length - 1; i >= 0; i--) {
        const line = lines[i] + '\n'
        kept += line.length
        if (kept > KEEP_BYTES) {
          startIdx = i + 1
          break
        }
      }
      const trimmed = lines.slice(startIdx).join('\n')
      writeFileSync(logFile, trimmed)
    }
  } catch {
    // trimming is optional
  }
}

function logSample(timestamp, data, logFile = LOG_FILE) {
  try {
    mkdirSync(dirname(logFile), { recursive: true })
    const line = JSON.stringify({ at: timestamp, app: 'brain-map', ...data }) + '\n'
    appendFileSync(logFile, line)
    try {
      if (statSync(logFile).size > MAX_BYTES) trimLog(logFile)
    } catch {
      /* ignore stat failures */
    }
  } catch {
    /* logging never crashes the app */
  }
}

function startCpuSampler({ interval = 5000, logFile = LOG_FILE } = {}) {
  let intervalHandle = null
  let initialized = false

  const sample = () => {
    try {
      const timestamp = new Date().toISOString()
      const metrics = app.getAppMetrics()

      if (!Array.isArray(metrics) || metrics.length === 0) {
        logSample(timestamp, { error: 'no metrics available' }, logFile)
        return
      }

      const processes = []
      for (const m of metrics) {
        if (!m || typeof m !== 'object') continue
        const cpu = m.cpu || {}
        if (typeof cpu.percentCPUUsage !== 'number') continue

        processes.push({
          pid: m.pid || -1,
          type: m.type || 'unknown',
          cpu: Number.isFinite(cpu.percentCPUUsage) ? cpu.percentCPUUsage : 0
        })
      }

      logSample(timestamp, { processes }, logFile)
    } catch (err) {
      logSample(new Date().toISOString(), { error: String(err) }, logFile)
    }
  }

  return {
    start() {
      if (initialized) return
      initialized = true
      sample()
      intervalHandle = setInterval(sample, interval)
    },
    stop() {
      if (intervalHandle) {
        clearInterval(intervalHandle)
        intervalHandle = null
      }
      initialized = false
    }
  }
}

module.exports = { startCpuSampler }
