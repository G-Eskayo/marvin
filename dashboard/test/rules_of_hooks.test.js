import { describe, it, expect } from 'vitest'
import { ESLint } from 'eslint'
import reactHooks from 'eslint-plugin-react-hooks'

// React's own rule: hooks run in the same order on every render. A hook after an early return (DashboardHome,
// 2026-10-09) passes every other test and blanks the whole window the moment data loads (React error #310).
describe('rules of hooks across the renderer', () => {
  it('no component calls a hook conditionally or after an early return', async () => {
    const eslint = new ESLint({
      overrideConfigFile: true,
      overrideConfig: [{
        files: ['**/*.js', '**/*.jsx'],
        languageOptions: { ecmaVersion: 'latest', sourceType: 'module', parserOptions: { ecmaFeatures: { jsx: true } } },
        plugins: { 'react-hooks': reactHooks },
        rules: { 'react-hooks/rules-of-hooks': 'error' }
      }]
    })
    const results = await eslint.lintFiles(['src/**/*.jsx', 'src/**/*.js'])
    const problems = results.flatMap((r) => r.messages.filter((m) => m.ruleId === 'react-hooks/rules-of-hooks' || m.fatal)
      .map((m) => `${r.filePath.split('/src/')[1]}:${m.line} ${m.message}`))
    expect(problems).toEqual([])
  }, 60_000)
})
