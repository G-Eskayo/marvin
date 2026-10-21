// The "Triggers over polling" guard (marvin#556): finds every timer and TTL in the dashboard's source so a test can
// hold them to an allowlist. CONTEXT.md "Triggers over polling" (decided 2026-10-03) says state changes are announced
// where the state is stored (gh_watch.js's ETag change-detector for GitHub, triggerHub.watchFiles for local files) and
// polling stays only as a backstop. marvin#554 re-added a 90 s re-read of PR checks anyway; a rule that is only
// remembered fails that way, so this one is read from the code.
//
// It parses (comments and strings can't match) and reports, per file:
//   interval      a setInterval reference in any form (call, alias, globalThis./window., destructured, imported from
//                 'timers'), or a call to a function, in this file or imported, that starts one
//   timeout-loop  a setTimeout that recurs: re-schedules its own function, sits in a loop, or is a sleep awaited in a
//                 loop or a self-calling function; also setTimeout passed around as a value (can't tell if it recurs)
//   ttl           a distinct TTL name declared, imported or used as a key (ttlFor, PENDING_CHECKS_TTL_MS, ...)
//   ui-clock      a setInterval/recurring setTimeout whose callback only calls this file's useState setters (and
//                 Date.now / Math.*): it repaints a clock and cannot reach the network. Allowed without an entry.
//   unparseable   the file could not be read as JS/TS, so it can't be verified (fails closed)
import { parse } from '@babel/parser'

const TIMERS = new Set(['setInterval', 'setTimeout'])
const GLOBAL_OBJECTS = new Set(['globalThis', 'window', 'global', 'self'])
const TIMER_MODULES = new Set(['timers', 'node:timers', 'timers/promises', 'node:timers/promises'])
const TTL_NAME = /ttl/i
const LOOPS = new Set(['ForStatement', 'ForInStatement', 'ForOfStatement', 'WhileStatement', 'DoWhileStatement'])
const FUNCTIONS = new Set(['FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression', 'ObjectMethod', 'ClassMethod', 'ClassPrivateMethod'])
const SKIP_KEYS = new Set(['loc', 'start', 'end', 'extra', 'leadingComments', 'trailingComments', 'innerComments', 'comments', 'tokens', 'errors'])

function pluginsFor(file) {
  if (/\.tsx$/.test(file)) return ['typescript', 'jsx']
  if (/\.[cm]?ts$/.test(file)) return ['typescript']
  return ['jsx']
}

function children(node) {
  const out = []
  for (const k of Object.keys(node)) {
    if (SKIP_KEYS.has(k)) continue
    const v = node[k]
    if (Array.isArray(v)) for (const c of v) { if (c && typeof c.type === 'string') out.push(c) }
    else if (v && typeof v.type === 'string') out.push(v)
  }
  return out
}

function walk(node, visit, ancestors = []) {
  visit(node, ancestors)
  ancestors.push(node)
  for (const c of children(node)) walk(c, visit, ancestors)
  ancestors.pop()
}

const keyName = (k) => (k?.type === 'Identifier' ? k.name : k?.type === 'StringLiteral' ? k.value : null)
const isFn = (n) => n && FUNCTIONS.has(n.type)
const lineOf = (n) => n.loc?.start.line ?? 0

// The name a function goes by: its own id, or the variable/param/property/assignment it is bound to. Inline
// anonymous functions (a useEffect body, a Promise executor) have none and are transparent.
function fnName(fn, parent) {
  if (fn.id?.name) return fn.id.name
  if (fn.type === 'ObjectMethod' || fn.type === 'ClassMethod') return keyName(fn.key)
  if (!parent) return null
  if (parent.type === 'VariableDeclarator' && parent.init === fn && parent.id.type === 'Identifier') return parent.id.name
  if (parent.type === 'AssignmentPattern' && parent.right === fn && parent.left.type === 'Identifier') return parent.left.name
  if (parent.type === 'AssignmentExpression' && parent.right === fn && parent.left.type === 'Identifier') return parent.left.name
  if ((parent.type === 'ObjectProperty' || parent.type === 'ClassProperty') && parent.value === fn) return keyName(parent.key)
  return null
}

// Nearest named function among the ancestors: [node, name] or null.
function nearestNamed(ancestors) {
  for (let i = ancestors.length - 1; i >= 0; i--) {
    if (isFn(ancestors[i])) {
      const name = fnName(ancestors[i], ancestors[i - 1])
      if (name) return { fn: ancestors[i], name, index: i }
    }
  }
  return null
}

function calledNames(node) {
  const names = new Set()
  walk(node, (n) => {
    if ((n.type === 'CallExpression' || n.type === 'OptionalCallExpression') && n.callee.type === 'Identifier') names.add(n.callee.name)
  })
  return names
}

// Is this Identifier a reference (a read of the binding), as opposed to a declaration, key or member property?
function isReference(node, parent) {
  if (!parent) return true
  switch (parent.type) {
    case 'MemberExpression': case 'OptionalMemberExpression': return parent.object === node || parent.computed
    case 'ObjectProperty': return parent.value === node && !(parent.computed === false && parent.key === node && !parent.shorthand)
    case 'ObjectMethod': case 'ClassMethod': case 'ClassProperty': case 'ClassPrivateMethod': return parent.computed && parent.key === node
    case 'VariableDeclarator': return parent.init === node
    case 'FunctionDeclaration': case 'FunctionExpression': case 'ArrowFunctionExpression': return parent.body === node
    case 'ImportSpecifier': case 'ImportDefaultSpecifier': case 'ImportNamespaceSpecifier': case 'ExportSpecifier': return false
    case 'LabeledStatement': case 'BreakStatement': case 'ContinueStatement': return false
    case 'AssignmentPattern': return parent.right === node
    default: return !parent.type.startsWith('TS')
  }
}

// Is this Identifier a name being bound by a destructuring pattern (not read)?
function inPattern(node, anc) {
  const parent = anc[anc.length - 1]
  const grand = anc[anc.length - 2]
  if (!parent) return false
  if (parent.type === 'ObjectProperty' && parent.value === node && grand?.type === 'ObjectPattern') return true
  if (parent.type === 'ArrayPattern' || parent.type === 'RestElement') return true
  if (parent.type === 'AssignmentPattern' && parent.left === node) return true
  return false
}

function isParam(node, parent) {
  return isFn(parent) && parent.params.includes(node)
}

// Per-file facts gathered before findings are judged: timer aliases, useState setters, imports, exports, named fns.
function collect(ast) {
  const timerAlias = new Map() // local name -> 'setInterval' | 'setTimeout' (imported from a timers module)
  const timerObjects = new Set(GLOBAL_OBJECTS) // namespace/default imports of a timers module
  const setters = new Map() // setter name -> state variable name (or null)
  const effectDeps = new Set() // identifiers named in a useEffect/useLayoutEffect dependency array
  const imports = new Map() // local -> { source, imported }  (imported: name | 'default' | '*')
  const exportsMap = new Map() // exported name -> local name
  const destructured = []
  const shadowed = new Set() // local bindings named setTimeout/setInterval that are not the global
  walk(ast, (n, anc) => {
    if (n.type === 'ImportDeclaration') {
      const src = n.source.value
      for (const s of n.specifiers) {
        if (TIMER_MODULES.has(src)) {
          if (s.type === 'ImportSpecifier' && TIMERS.has(keyName(s.imported))) timerAlias.set(s.local.name, keyName(s.imported))
          else if (s.type !== 'ImportSpecifier') timerObjects.add(s.local.name)
        }
        imports.set(s.local.name, { source: src, imported: s.type === 'ImportSpecifier' ? keyName(s.imported) : s.type === 'ImportDefaultSpecifier' ? 'default' : '*' })
      }
    }
    // const { setInterval: every } = globalThis -> every is the timer; destructured from anything else (a param,
    // deps) it is someone's injected value and shadows the global.
    if (n.type === 'ObjectPattern') {
      const parent = anc[anc.length - 1]
      const from = parent?.type === 'VariableDeclarator' && parent.id === n && parent.init?.type === 'Identifier' ? parent.init.name : null
      for (const pr of n.properties) {
        const k = pr.type === 'ObjectProperty' && keyName(pr.key)
        const local = pr.value?.type === 'AssignmentPattern' ? pr.value.left : pr.value
        if (TIMERS.has(k) && local?.type === 'Identifier') destructured.push({ local: local.name, timer: k, from })
      }
    }
    if (n.type === 'VariableDeclarator' && n.id.type === 'ArrayPattern' && n.init?.type === 'CallExpression') {
      const c = n.init.callee
      const hook = c.type === 'Identifier' ? c.name : c.type === 'MemberExpression' ? keyName(c.property) : null
      const set = n.id.elements[1]
      if ((hook === 'useState' || hook === 'useReducer') && set?.type === 'Identifier') {
        const state = n.id.elements[0]
        setters.set(set.name, state?.type === 'Identifier' ? state.name : null)
      }
    }
    if (n.type === 'CallExpression') {
      const c = n.callee
      const hook = c.type === 'Identifier' ? c.name : c.type === 'MemberExpression' ? keyName(c.property) : null
      const deps = n.arguments[1]
      if ((hook === 'useEffect' || hook === 'useLayoutEffect') && deps?.type === 'ArrayExpression') {
        for (const d of deps.elements) walk(d || { type: 'Null' }, (x) => x.type === 'Identifier' && effectDeps.add(x.name))
      }
    }
    if (n.type === 'ExportNamedDeclaration') {
      const d = n.declaration
      if (d?.id?.name) exportsMap.set(d.id.name, d.id.name)
      if (d?.type === 'VariableDeclaration') for (const v of d.declarations) if (v.id.type === 'Identifier') exportsMap.set(v.id.name, v.id.name)
      if (!n.source) for (const s of n.specifiers || []) if (s.local) exportsMap.set(keyName(s.exported), s.local.name)
    }
    if (n.type === 'ExportDefaultDeclaration') {
      const d = n.declaration
      if (d.type === 'Identifier') exportsMap.set('default', d.name)
      else if (d.id?.name) exportsMap.set('default', d.id.name)
    }
  })
  for (const d of destructured) {
    if (d.from && timerObjects.has(d.from)) timerAlias.set(d.local, d.timer)
    else shadowed.add(d.local)
  }
  return { timerAlias, timerObjects, setters, effectDeps, imports, exportsMap, shadowed }
}

// Which timer (if any) does this node name? Handles setInterval, an imported alias, globalThis.setInterval,
// window['setInterval'], timers.setInterval. Returns 'setInterval' | 'setTimeout' | null.
function timerNamed(node, anc, facts, shadowed) {
  const parent = anc[anc.length - 1]
  if (node.type === 'Identifier' && isReference(node, parent) && !isParam(node, parent) && !inPattern(node, anc)) {
    if (facts.timerAlias.has(node.name)) return facts.timerAlias.get(node.name)
    if (TIMERS.has(node.name) && !shadowed.has(node.name)) return node.name
  }
  if ((node.type === 'MemberExpression' || node.type === 'OptionalMemberExpression') && node.object.type === 'Identifier' && facts.timerObjects.has(node.object.name)) {
    const prop = node.computed ? (node.property.type === 'StringLiteral' ? node.property.value : null) : keyName(node.property)
    if (TIMERS.has(prop)) return prop
  }
  return null
}

// The narrow UI-clock rule: the callback is an inline function whose every call is a useState setter of this file
// (whose state no useEffect depends on, so it can't drive a refetch), Date.now / performance.now / Math.*, or new Date.
function isUiClock(callback, facts) {
  if (!callback || !(callback.type === 'ArrowFunctionExpression' || callback.type === 'FunctionExpression') || callback.async) return false
  let ok = true
  walk(callback.body, (n) => {
    if (!ok) return
    if (n.type === 'AwaitExpression' || n.type === 'YieldExpression' || n.type === 'TaggedTemplateExpression' || n.type === 'Import') ok = false
    if (n.type === 'NewExpression' && !(n.callee.type === 'Identifier' && n.callee.name === 'Date')) ok = false
    if (n.type === 'CallExpression' || n.type === 'OptionalCallExpression') {
      const c = n.callee
      if (c.type === 'Identifier' && facts.setters.has(c.name)) {
        const state = facts.setters.get(c.name)
        if (state && facts.effectDeps.has(state)) ok = false
      } else if (c.type === 'MemberExpression' && !c.computed && c.object.type === 'Identifier' &&
        ((c.object.name === 'Date' && keyName(c.property) === 'now') || (c.object.name === 'performance' && keyName(c.property) === 'now') || c.object.name === 'Math')) {
        // pure
      } else ok = false
    }
  })
  return ok
}

// Is the node inside a loop body, looking through inline anonymous functions up to the nearest named function?
function inLoop(ancestors) {
  for (let i = ancestors.length - 1; i >= 0; i--) {
    const a = ancestors[i]
    if (LOOPS.has(a.type)) return true
    if (isFn(a) && fnName(a, ancestors[i - 1])) return false
  }
  return false
}

// Is a setTimeout call's callback the resolver of an enclosing `new Promise(...)` (a sleep)?
function insidePromise(ancestors) {
  return ancestors.some((a) => a.type === 'NewExpression' && a.callee.type === 'Identifier' && a.callee.name === 'Promise')
}

function parseFile(code, file) {
  return parse(code, { sourceType: 'unambiguous', plugins: pluginsFor(file), allowReturnOutsideFunction: true, allowAwaitOutsideFunction: true, errorRecovery: false })
}

// Pass 1 over one file: the facts, and which of its named functions start an interval or are sleeps.
function prepare(code, file) {
  let ast
  try { ast = parseFile(code, file) } catch (e) { return { file, error: String(e.message || e) } }
  const facts = collect(ast)
  const starters = new Set() // named functions holding a non-UI-clock setInterval
  const delays = new Set() // named functions holding a sleep (setTimeout inside new Promise)
  const shadowed = new Set(facts.shadowed)
  walk(ast, (n, anc) => {
    const parent = anc[anc.length - 1]
    // A local binding named setTimeout/setInterval (a param or variable) is someone's injected fake, not the global.
    if (n.type === 'Identifier' && TIMERS.has(n.name) && ((parent?.type === 'VariableDeclarator' && parent.id === n) || isParam(n, parent))) shadowed.add(n.name)
  })
  walk(ast, (n, anc) => {
    const parent = anc[anc.length - 1]
    const t = timerNamed(n, anc, facts, shadowed)
    if (!t) return
    const named = nearestNamed(anc)
    if (!named) return
    const call = parent && (parent.type === 'CallExpression' || parent.type === 'OptionalCallExpression') && parent.callee === n ? parent : null
    if (t === 'setInterval' && !(call && isUiClock(call.arguments[0], facts))) starters.add(named.name)
    if (t === 'setTimeout' && call && insidePromise(anc.slice(named.index))) delays.add(named.name)
  })
  return { file, ast, facts, starters, delays, shadowed }
}

function resolveImport(fromFile, source, known) {
  if (!source.startsWith('.')) return null
  const dir = fromFile.split('/').slice(0, -1)
  for (const part of source.split('/')) {
    if (part === '.' || part === '') continue
    if (part === '..') dir.pop()
    else dir.push(part)
  }
  const base = dir.join('/')
  for (const cand of [base, `${base}.js`, `${base}.jsx`, `${base}.mjs`, `${base}.ts`, `${base}.tsx`, `${base}/index.js`]) if (known.has(cand)) return cand
  return null
}

// Pass 2 over one file: the findings, given every file's pass-1 result (for imported helpers).
function judge(p, prepared) {
  if (p.error) return [{ kind: 'unparseable', line: 0, why: `could not parse: ${p.error}` }]
  const { ast, facts, starters, delays, shadowed } = p
  const findings = []
  const add = (kind, node, why) => findings.push({ kind, line: lineOf(node), why })

  // A callee resolved to a helper elsewhere: 'starter' | 'delay' | null.
  function importedRole(local, member) {
    const imp = facts.imports.get(local)
    if (!imp) return null
    const target = prepared.get(resolveImport(p.file, imp.source, prepared))
    if (!target || target.error) return null
    const exported = imp.imported === '*' ? member : imp.imported
    const localThere = exported && target.facts.exportsMap.get(exported)
    if (!localThere) return null
    if (target.starters.has(localThere)) return 'starter'
    if (target.delays.has(localThere)) return 'delay'
    return null
  }

  const selfCalls = new Map()
  const callsItself = (named) => {
    if (!selfCalls.has(named.fn)) selfCalls.set(named.fn, calledNames(named.fn.body).has(named.name))
    return selfCalls.get(named.fn)
  }

  const ttlNames = new Map()
  walk(ast, (n, anc) => {
    const parent = anc[anc.length - 1]

    // TTL names, counted once per name per file.
    let ttl = null
    if (n.type === 'Identifier' && TTL_NAME.test(n.name) && !(parent?.type === 'MemberExpression' && parent.property === n && !parent.computed)) ttl = n.name
    if ((n.type === 'StringLiteral') && parent && (parent.type === 'ObjectProperty' || parent.type === 'ClassProperty') && parent.key === n && TTL_NAME.test(n.value)) ttl = n.value
    if (ttl && !ttlNames.has(ttl)) ttlNames.set(ttl, n)

    // Raw timers.
    const t = timerNamed(n, anc, facts, shadowed)
    if (t) {
      const call = parent && (parent.type === 'CallExpression' || parent.type === 'OptionalCallExpression') && parent.callee === n ? parent : null
      const named = nearestNamed(anc)
      if (t === 'setInterval') {
        if (call && isUiClock(call.arguments[0], facts)) add('ui-clock', n, 'setInterval that only repaints (useState setters, Date.now)')
        else add('interval', n, call ? 'setInterval' : 'setInterval used as a value (an alias or an injected default)')
      } else if (!call) {
        add('timeout-loop', n, 'setTimeout used as a value: it cannot be told whether it recurs')
      } else {
        const cb = call.arguments[0]
        let recurs = null
        if (named && cb?.type === 'Identifier' && cb.name === named.name) recurs = `setTimeout re-schedules ${named.name}`
        else if (named && isFn(cb) && calledNames(cb.body).has(named.name)) recurs = `setTimeout's callback calls ${named.name} again`
        else if (inLoop(anc)) recurs = 'setTimeout inside a loop'
        else if (named && callsItself(named) && insidePromise(anc.slice(named.index))) recurs = `sleep inside ${named.name}, which calls itself`
        if (recurs) {
          if (isUiClock(cb, facts)) add('ui-clock', n, `${recurs}, but only repaints`)
          else add('timeout-loop', n, recurs)
        }
      }
      return
    }

    // Calls to helpers: a function that starts an interval, or a sleep awaited in a loop / self-calling function.
    if (n.type === 'CallExpression' || n.type === 'OptionalCallExpression') {
      const c = n.callee
      let name = null
      let role = null
      if (c.type === 'Identifier') {
        name = c.name
        role = facts.imports.has(name) ? importedRole(name) : starters.has(name) ? 'starter' : delays.has(name) ? 'delay' : null
      } else if (c.type === 'MemberExpression' && !c.computed && c.object.type === 'Identifier' && facts.imports.get(c.object.name)?.imported === '*') {
        name = `${c.object.name}.${keyName(c.property)}`
        role = importedRole(c.object.name, keyName(c.property))
      }
      if (!role) return
      const named = nearestNamed(anc)
      if (role === 'starter' && named?.name !== name) add('interval', n, `calls ${name}, which starts a setInterval`)
      if (role === 'delay' && (inLoop(anc) || (named && named.name !== name && callsItself(named)))) add('timeout-loop', n, `sleeps (${name}) in a loop`)
    }
  })
  for (const [name, node] of ttlNames) add('ttl', node, `TTL name ${name}`)
  return findings.sort((a, b) => a.line - b.line)
}

// Analyse a set of files together (so an imported helper is seen through). files: [{ path, code }].
// Returns Map(path -> findings[]).
export function scanFiles(files) {
  const prepared = new Map(files.map((f) => [f.path, prepare(f.code, f.path)]))
  const out = new Map()
  for (const [path, p] of prepared) out.set(path, judge(p, prepared))
  return out
}

export function analyzeSource(code, file = 'x.js') {
  return scanFiles([{ path: file, code }]).get(file)
}

export const GUIDANCE = [
  'CONTEXT.md "Triggers over polling" (decided 2026-10-03): trigger at the place state is stored; polling stays only as a backstop.',
  '  GitHub state: webhook-server/gh_watch.js already sends one conditional (ETag) request per repo every ~20 s; a 304 is free.',
  '  React to its change ping (the app\'s /refresh topics, window.api.triggers / window.api.mr.onRefresh) instead of a timer or TTL.',
  '  Local files: triggerHub.watchFiles in electron/main/triggers.js.',
  'If this really is a backstop, a UI clock, or a bounded wait with no event to wait on, add it to ALLOWLIST in',
  'dashboard/test/polling_guard.test.js with the count and a one-line reason.'
].join('\n')

// Compare findings with the allowlist: { 'path': { kind: [count, reason] } }. Returns problem strings ([] = ok).
export function checkAllowlist(results, allowlist) {
  const problems = []
  const counted = new Map()
  for (const [path, findings] of results) {
    for (const f of findings) {
      if (f.kind === 'ui-clock') continue
      const k = `${path}\0${f.kind}`
      if (!counted.has(k)) counted.set(k, [])
      counted.get(k).push(f)
    }
  }
  for (const [path, kinds] of Object.entries(allowlist)) {
    for (const [kind, entry] of Object.entries(kinds)) {
      const [count, reason] = Array.isArray(entry) ? entry : [entry, '']
      if (typeof reason !== 'string' || reason.trim().length < 10) problems.push(`${path} ${kind}: allowlist entry needs a one-line reason`)
      const have = counted.get(`${path}\0${kind}`) || []
      if (have.length < count) problems.push(`${path} ${kind}: allowlist says ${count}, the code has ${have.length}. Lower or remove the entry (a stale entry would let a new one in unseen).`)
    }
  }
  for (const [k, have] of counted) {
    const [path, kind] = k.split('\0')
    const count = allowlist[path]?.[kind]?.[0] ?? 0
    if (have.length > count) {
      const where = have.map((f) => `    ${path}:${f.line} ${f.kind}: ${f.why}`).join('\n')
      problems.push(`${path}: ${have.length} ${kind} finding(s), ${count} allowlisted\n${where}`)
    }
  }
  return problems
}
