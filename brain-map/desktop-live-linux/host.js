// Pure logic for the Linux live wallpaper (mac-mini-2012, ADR 0069): the same page hooks the macOS DesktopLive host
// calls (DesktopLive/main.swift), built as JavaScript strings. Every value goes through JSON.stringify, so a skill
// name or device id can never break out of the call it is passed to.
'use strict'

function call(fn, ...args) {
  return `if (window.${fn}) window.${fn}(${args.map((a) => JSON.stringify(a)).join(', ')});`
}

// New complete lines since the last read. A file that shrank was trimmed or rotated: start counting again.
function newLines(text, lastCount) {
  const lines = (text || '').split('\n').filter((l) => l.length > 0)
  if (lines.length < lastCount) return { lines: [], count: lines.length }
  return { lines: lines.slice(lastCount), count: lines.length }
}

function parse(line) {
  try { return JSON.parse(line) } catch { return null }
}

function activityCalls(lines) {
  return lines.map(parse).filter((o) => o && typeof o.skill === 'string').map((o) => call('triggerActivity', o.skill))
}

function demoCalls(lines) {
  const out = []
  for (const o of lines.map(parse)) {
    if (!o) continue
    if (o.type === 'add' && o.node && typeof o.parent === 'string') out.push(call('demoAddNode', o.node, o.parent))
    else if (o.type === 'remove' && typeof o.id === 'string') out.push(call('demoRemoveNode', o.id))
  }
  return out
}

// null when tree-data.json doesn't parse (mid-write): the caller reloads the page instead of staying stale.
function treeCall(text) {
  const o = parse(text)
  if (!o || typeof o !== 'object') return null
  return call('updateTreeData', o.tree || {}, o.synapses || [])
}

// `tailscale status --json` + marvin-network.json -> calls for devices whose online state changed.
function livenessCalls(status, registry, last) {
  const byHost = {}
  for (const [id, info] of Object.entries((registry && registry.devices) || {})) {
    if (info && typeof info.tailscale_hostname === 'string') byHost[info.tailscale_hostname] = id
  }
  const prefix = (dns) => String(dns || '').split('.')[0]
  const seen = {}
  if (status && status.Self && status.Self.DNSName) seen[prefix(status.Self.DNSName)] = status.Self.Online !== false
  for (const p of Object.values((status && status.Peer) || {})) {
    if (p && p.DNSName) seen[prefix(p.DNSName)] = p.Online === true
  }
  const calls = []
  const next = { ...last }
  for (const [host, id] of Object.entries(byHost)) {
    const online = seen[host] === true
    if (next[id] === online) continue
    next[id] = online
    calls.push(call('setDeviceStatus', id, online))
  }
  return { calls, last: next }
}

module.exports = { call, newLines, activityCalls, demoCalls, treeCall, livenessCalls }
