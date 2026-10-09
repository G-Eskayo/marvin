/**
 * Upsert a marked section in a GitHub PR body.
 * Replaces if it exists, appends if it doesn't.
 */
import { promisify } from 'util'
import { execFile } from 'child_process'

const execFileAsync = promisify(execFile)

/**
 * Merge a mutation section into a PR body between markers.
 * Returns the new body.
 */
export function mergeMutationSection(currentBody, newSection) {
  const startMarker = '<!-- marvin:mutation-check -->'
  const endMarker = '<!-- /marvin:mutation-check -->'
  const trimmedSection = newSection.trim()

  if (currentBody.includes(startMarker) && currentBody.includes(endMarker)) {
    // Replace existing section
    const before = currentBody.split(startMarker)[0]
    const after = currentBody.split(endMarker)[1] || ''
    return `${before}${startMarker}\n${trimmedSection}\n${endMarker}${after}`
  } else {
    // Append new section
    return `${currentBody.trimEnd()}\n\n${startMarker}\n${trimmedSection}\n${endMarker}\n`
  }
}

/**
 * Upsert a mutation check section in a GitHub PR body.
 * Fetches the current body, updates it, and writes it back.
 */
export async function upsertMutationSection(prUrl, newSection, exec = execFileAsync) {
  try {
    // Fetch current PR body
    const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'body'])
    const { body: currentBody = '' } = JSON.parse(stdout)

    // Merge the new section
    const updatedBody = mergeMutationSection(currentBody, newSection)

    // If nothing changed, skip the update
    if (updatedBody === currentBody) {
      return
    }

    // Write back the updated body
    await exec('gh', ['pr', 'edit', prUrl, '--body', updatedBody])
  } catch (e) {
    // Fail open: a GitHub hiccup doesn't block the merge
    console.error(`[pr_body_section] failed to upsert mutation section: ${String(e?.message || e).slice(0, 200)}`)
  }
}

/**
 * Render a mutation result into a markdown section for the PR body.
 */
export function renderMutationSection(result) {
  if (!result) {
    return '## Mutation Score\n\nNo mutation check result available.\n'
  }

  if (result.status !== 'ok') {
    return `## Mutation Score\n\n⚠️ Could not measure test quality (${result.reason || 'unknown error'}).\n`
  }

  if (result.mutants_total === 0) {
    return '## Mutation Score\n\n✅ No mutable lines in this PR (pure configuration, docs, or test changes).\n'
  }

  const survivedCount = Array.isArray(result.survived) ? result.survived.length : 0
  const score = result.killed + survivedCount
  const scorePercent = score > 0 ? ((result.killed / score) * 100).toFixed(0) : 0

  let md = `## Mutation Score\n\n**${scorePercent}%** (${result.killed} of ${score} mutants killed)\n`

  // Top survivors (capped at ~20)
  if (result.survived && result.survived.length > 0) {
    md += '\n### Surviving Mutants\n\n'
    md += '| File | Line | Operator | Snippet |\n'
    md += '|------|------|----------|----------|\n'

    const survivors = result.survived.slice(0, 20)
    for (const mutant of survivors) {
      // Escape single pipes (not ||, not |==|, etc.)
      const snippet = (mutant.snippet || '').slice(0, 40).replace(/(?<!\|)\|(?!\|)/g, '\\|')
      md += `| ${mutant.file} | ${mutant.line} | \`${mutant.operator}\` | ${snippet} |\n`
    }

    if (result.survived.length > 20) {
      md += `\n... and ${result.survived.length - 20} more.\n`
    }
  }

  // Unmeasured (no test file) - just note the count, don't list
  if (result.unmeasured && result.unmeasured.length > 0) {
    md += `\n⚠️ ${result.unmeasured.length} file(s) have no test file and were unmeasured.\n`
  }

  return md
}
