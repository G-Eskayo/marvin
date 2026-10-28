import { AddonNotSetUp } from './AddonNotSetUp'

export function AddonGate({ addon, enabled, onEnable, children }) {
  if (enabled === null || enabled === undefined) {
    return null
  }

  if (!enabled) {
    return <AddonNotSetUp addon={addon} onEnable={onEnable} />
  }

  return children
}
