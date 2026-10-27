import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AddonNotSetUp } from '../src/components/AddonNotSetUp.jsx'

const html = (props) => renderToStaticMarkup(<AddonNotSetUp onEnable={() => {}} {...props} />)

// The element tree, walked without a DOM: find the first element matching `test`.
function find(node, test) {
  if (!node || typeof node !== 'object') return null
  if (Array.isArray(node)) {
    for (const n of node) { const hit = find(n, test); if (hit) return hit }
    return null
  }
  if (test(node)) return node
  return find(node.props?.children, test)
}

describe('AddonNotSetUp', () => {
  it.each([
    ['portfolio', 'Portfolio', 'Project portfolio and web updates'],
    ['resume_tailor', 'Resume Tailor', 'Job application packages and resume tailoring'],
    ['seal_ingest', 'Seal Ingest', 'Seal Speak beta feedback collection']
  ])('names the %s add-on and what it does', (addon, name, description) => {
    const out = html({ addon })
    expect(out).toContain(`<h2>${name}</h2>`)
    expect(out).toContain(description)
    expect(out).toContain('This add-on is not yet enabled.')
  })

  it('tells the user how to turn it on by hand, naming that add-on’s own flag', () => {
    const out = html({ addon: 'resume_tailor' })
    expect(out).toContain('~/.agents/instance/instance.json')
    expect(out).toContain('features.resume_tailor')
    expect(out).not.toContain('features.portfolio')
  })

  it('the Enable button asks for exactly the add-on shown', () => {
    const onEnable = vi.fn()
    const button = find(AddonNotSetUp({ addon: 'portfolio', onEnable }), (n) => n.type === 'button')
    expect(button.props.children).toBe('Enable Add-on')
    button.props.onClick()
    expect(onEnable).toHaveBeenCalledTimes(1)
    expect(onEnable).toHaveBeenCalledWith('portfolio')
  })

  it.each([['unknown'], [''], [undefined], ['__proto__'], ['constructor']])(
    'an add-on it does not know (%s) says so and offers no Enable button', (addon) => {
      const out = html({ addon })
      expect(out).toContain('Unknown add-on')
      expect(out).not.toContain('<button')
    })

  it('escapes an add-on name instead of rendering it as markup', () => {
    const out = html({ addon: '<img src=x onerror=alert(1)>' })
    expect(out).not.toContain('<img')
    expect(out).toContain('&lt;img')
  })
})
