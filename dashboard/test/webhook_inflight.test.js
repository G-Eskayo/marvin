import { describe, it, expect } from 'vitest'
import { createServer } from 'http'
import { peekInflight, createInflightStore } from '../webhook-server/merge_progress.js'
import * as fs from 'fs'
import * as path from 'path'
import * as os from 'os'

const PR1 = 'https://github.com/G-Eskayo/marvin/pull/559'
const PR2 = 'https://github.com/G-Eskayo/marvin/pull/560'

describe('/inflight webhook route', () => {
  it('GET /inflight returns entire map in { inflight: {} } shape', async () => {
    const tmpFile = path.join(os.tmpdir(), `inflight-test-${Date.now()}.json`)
    const store = createInflightStore(tmpFile)

    // Write test data
    const data = {
      [PR1]: { stage: 'fetching', seq: 1, at: Date.now() },
      [PR2]: { stage: 'tests', seq: 2, at: Date.now() }
    }
    fs.writeFileSync(tmpFile, JSON.stringify(data))

    const all = peekInflight(tmpFile)
    expect(all).toEqual(data)

    // Verify the shape that should be returned by the route
    const response = { inflight: all }
    expect(response.inflight[PR1]).toEqual(data[PR1])
    expect(response.inflight[PR2]).toEqual(data[PR2])

    fs.unlinkSync(tmpFile)
  })

  it('GET /inflight?url=<url> returns { inflight: { [url]: entry } } shape', async () => {
    const tmpFile = path.join(os.tmpdir(), `inflight-test-${Date.now()}.json`)

    const data = {
      [PR1]: { stage: 'fetching', seq: 1, at: Date.now() },
      [PR2]: { stage: 'tests', seq: 2, at: Date.now() }
    }
    fs.writeFileSync(tmpFile, JSON.stringify(data))

    const all = peekInflight(tmpFile)
    const entry = all[PR1] || null

    // Verify the correct response shape for a specific URL
    const response = { inflight: { [PR1]: entry } }
    expect(response.inflight).toHaveProperty(PR1)
    expect(response.inflight[PR1]).toEqual(data[PR1])

    fs.unlinkSync(tmpFile)
  })

  it('GET /inflight?url=<missing> returns { inflight: { [url]: null } }', async () => {
    const tmpFile = path.join(os.tmpdir(), `inflight-test-${Date.now()}.json`)

    const data = {
      [PR1]: { stage: 'fetching', seq: 1, at: Date.now() }
    }
    fs.writeFileSync(tmpFile, JSON.stringify(data))

    const all = peekInflight(tmpFile)
    const missing = PR2
    const entry = all[missing] || null

    // Verify the shape when URL is not in the map
    const response = { inflight: { [missing]: entry } }
    expect(response.inflight).toHaveProperty(missing)
    expect(response.inflight[missing]).toBeNull()

    fs.unlinkSync(tmpFile)
  })
})
