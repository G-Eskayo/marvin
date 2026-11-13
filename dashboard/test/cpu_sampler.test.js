import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mkdtempSync, rmSync, readFileSync, writeFileSync, statSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'

// Mock electron's app module
const mockApp = {
  getAppMetrics: vi.fn(),
  disableHardwareAcceleration: vi.fn()
}

vi.mock('electron', () => ({
  app: mockApp
}))

describe('cpu_sampler', () => {
  let testLogDir
  let testLogFile

  beforeEach(() => {
    testLogDir = mkdtempSync(path.join(tmpdir(), 'cpu-sampler-'))
    testLogFile = path.join(testLogDir, 'cpu-sampler.log')
  })

  // Test 6: Malformed or missing metrics handling
  describe('test 6: resilience to malformed metrics', () => {
    it('handles empty metrics array without crashing', async () => {
      mockApp.getAppMetrics.mockReturnValue([])
      const { startCpuSampler } = await import('../electron/main/cpu_sampler.js')
      const sampler = startCpuSampler({ interval: 1000, logFile: testLogFile })
      sampler.start()
      await new Promise(r => setTimeout(r, 100))
      sampler.stop()
      expect(mockApp.getAppMetrics).toHaveBeenCalled()
    })

    it('skips metrics missing the cpu.percentCPUUsage field', async () => {
      mockApp.getAppMetrics.mockReturnValue([
        { pid: 1, type: 'renderer' },
        { pid: 2, type: 'gpu', cpu: {} },
        { pid: 3, type: 'utility', cpu: { percentCPUUsage: 10.5 } }
      ])
      const { startCpuSampler } = await import('../electron/main/cpu_sampler.js')
      const sampler = startCpuSampler({ interval: 1000, logFile: testLogFile })
      sampler.start()
      await new Promise(r => setTimeout(r, 100))
      sampler.stop()
      const logContent = readFileSync(testLogFile, 'utf-8')
      const lastLine = logContent.trim().split('\n').pop()
      const data = JSON.parse(lastLine)
      expect(data.processes).toHaveLength(1)
      expect(data.processes[0].pid).toBe(3)
    })

    it('skips metrics with non-numeric percentCPUUsage', async () => {
      mockApp.getAppMetrics.mockReturnValue([
        { pid: 1, type: 'renderer', cpu: { percentCPUUsage: 'invalid' } },
        { pid: 2, type: 'gpu', cpu: { percentCPUUsage: 25.3 } }
      ])
      const { startCpuSampler } = await import('../electron/main/cpu_sampler.js')
      const sampler = startCpuSampler({ interval: 1000, logFile: testLogFile })
      sampler.start()
      await new Promise(r => setTimeout(r, 100))
      sampler.stop()
      const logContent = readFileSync(testLogFile, 'utf-8')
      const lastLine = logContent.trim().split('\n').pop()
      const data = JSON.parse(lastLine)
      expect(data.processes).toHaveLength(1)
      expect(data.processes[0].pid).toBe(2)
      expect(data.processes[0].cpu).toBe(25.3)
    })

    it('never crashes on app.getAppMetrics() exceptions', async () => {
      mockApp.getAppMetrics.mockImplementation(() => { throw new Error('metrics unavailable') })
      const { startCpuSampler } = await import('../electron/main/cpu_sampler.js')
      const sampler = startCpuSampler({ interval: 1000, logFile: testLogFile })
      sampler.start()
      await new Promise(r => setTimeout(r, 100))
      sampler.stop()
      const logContent = readFileSync(testLogFile, 'utf-8')
      expect(logContent).toContain('error')
    })

    it('log file never grows unboundedly (respects MAX_BYTES)', async () => {
      // Pre-populate log file to just under MAX_BYTES, then verify trimming happens
      const largeContent = JSON.stringify({ at: new Date().toISOString(), app: 'dashboard', test: 'x'.repeat(10000) }) + '\n'
      const MAX_BYTES = 50 * 1024 * 1024
      const KEEP_BYTES = 40 * 1024 * 1024
      let fileContent = ''
      // Create a file that's just over 40MB (KEEP_BYTES)
      while (fileContent.length < KEEP_BYTES + 100000) {
        fileContent += largeContent
      }
      writeFileSync(testLogFile, fileContent)

      mockApp.getAppMetrics.mockReturnValue([
        { pid: 1, type: 'renderer', cpu: { percentCPUUsage: 5 } }
      ])
      const { startCpuSampler } = await import('../electron/main/cpu_sampler.js')
      const sampler = startCpuSampler({ interval: 10, logFile: testLogFile })
      sampler.start()
      // Let it run long enough for trimming to trigger
      await new Promise(r => setTimeout(r, 100))
      sampler.stop()
      // Check that the log was trimmed (should be under 41MB, not 40MB+new data)
      const stats = statSync(testLogFile)
      expect(stats.size).toBeLessThan(41 * 1024 * 1024)
    })

    it('tags each log line with app name', async () => {
      mockApp.getAppMetrics.mockReturnValue([
        { pid: 1, type: 'renderer', cpu: { percentCPUUsage: 5 } }
      ])
      const { startCpuSampler } = await import('../electron/main/cpu_sampler.js')
      const sampler = startCpuSampler({ interval: 1000, logFile: testLogFile })
      sampler.start()
      await new Promise(r => setTimeout(r, 100))
      sampler.stop()
      const logContent = readFileSync(testLogFile, 'utf-8')
      const lines = logContent.trim().split('\n').filter(l => l.length > 0)
      for (const line of lines) {
        const data = JSON.parse(line)
        expect(data.app).toBe('dashboard')
      }
    })
  })

  // Test 7: Hardware acceleration disable gating
  describe('test 7: disableHardwareAcceleration() gating', () => {
    it('sampler never calls disableHardwareAcceleration itself', async () => {
      // The app.disableHardwareAcceleration() is a one-time call in main.js
      // based on device identity, not called by the sampler.
      // This test verifies the sampler does not try to manage HW acceleration.
      const disableHwAccelSpy = vi.spyOn(mockApp, 'disableHardwareAcceleration')
      mockApp.getAppMetrics.mockReturnValue([
        { pid: 1, type: 'renderer', cpu: { percentCPUUsage: 5 } }
      ])
      const { startCpuSampler } = await import('../electron/main/cpu_sampler.js')
      const sampler = startCpuSampler({ interval: 1000, logFile: testLogFile })
      sampler.start()
      await new Promise(r => setTimeout(r, 100))
      sampler.stop()
      // Sampler should never call disableHardwareAcceleration
      expect(disableHwAccelSpy).not.toHaveBeenCalled()
    })

    it('sampler works correctly when HW acceleration is disabled', async () => {
      // Simulate that disableHardwareAcceleration was already called
      mockApp.disableHardwareAcceleration()
      mockApp.getAppMetrics.mockReturnValue([
        { pid: 1, type: 'renderer', cpu: { percentCPUUsage: 3.5 } }
      ])
      const { startCpuSampler } = await import('../electron/main/cpu_sampler.js')
      const sampler = startCpuSampler({ interval: 1000, logFile: testLogFile })
      sampler.start()
      await new Promise(r => setTimeout(r, 100))
      sampler.stop()
      // Should still log metrics successfully
      const logContent = readFileSync(testLogFile, 'utf-8')
      expect(logContent).toContain('renderer')
    })
  })

  // Test 8: Concurrency guard
  describe('test 8: concurrency guard (double-init protection)', () => {
    it('sampler start() is idempotent; calling twice does not create double samples', async () => {
      mockApp.getAppMetrics.mockReturnValue([
        { pid: 1, type: 'renderer', cpu: { percentCPUUsage: 5 } }
      ])
      const { startCpuSampler } = await import('../electron/main/cpu_sampler.js')
      const sampler = startCpuSampler({ interval: 50, logFile: testLogFile })
      sampler.start()
      sampler.start()  // second call should be ignored
      await new Promise(r => setTimeout(r, 200))
      sampler.stop()
      const logContent = readFileSync(testLogFile, 'utf-8')
      const lines = logContent.trim().split('\n').filter(l => l.length > 0)
      // Should have roughly 4-5 samples (200ms / 50ms interval) + 1 initial, not 8-10
      expect(lines.length).toBeLessThan(10)
    })

    it('sampler stop() is idempotent', async () => {
      mockApp.getAppMetrics.mockReturnValue([
        { pid: 1, type: 'renderer', cpu: { percentCPUUsage: 5 } }
      ])
      const { startCpuSampler } = await import('../electron/main/cpu_sampler.js')
      const sampler = startCpuSampler({ interval: 1000, logFile: testLogFile })
      sampler.start()
      sampler.stop()
      sampler.stop()  // second call should not throw
      expect(mockApp.getAppMetrics.mock.calls.length).toBeGreaterThanOrEqual(1)
    })
  })

  // Test: Custom logFile directory creation
  describe('custom logFile directory handling', () => {
    it('creates directory of custom logFile, not default LOG_DIR', async () => {
      // Use a completely different temporary directory to ensure we're not using LOG_DIR
      const customDir = mkdtempSync(path.join(tmpdir(), 'custom-log-'))
      const customLogFile = path.join(customDir, 'custom', 'nested', 'log.json')

      mockApp.getAppMetrics.mockReturnValue([
        { pid: 1, type: 'renderer', cpu: { percentCPUUsage: 5 } }
      ])
      const { startCpuSampler } = await import('../electron/main/cpu_sampler.js')
      const sampler = startCpuSampler({ interval: 1000, logFile: customLogFile })
      sampler.start()
      await new Promise(r => setTimeout(r, 100))
      sampler.stop()

      // Verify the nested directory was created
      const stat = statSync(customLogFile.split('/').slice(0, -1).join('/'))
      expect(stat.isDirectory()).toBe(true)

      // Verify the log file was written to the custom location
      expect(readFileSync(customLogFile, 'utf-8')).toContain('dashboard')

      // Cleanup
      rmSync(customDir, { recursive: true, force: true })
    })
  })

  afterEach(() => {
    mockApp.getAppMetrics.mockReset()
    try {
      rmSync(testLogDir, { recursive: true, force: true })
    } catch {
      /* cleanup may fail if still open */
    }
  })
})
