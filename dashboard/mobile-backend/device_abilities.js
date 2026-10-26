// Map of device types to their capabilities.
// Capabilities from CONTEXT.md: show, touch, listen, speak

const DEVICE_ABILITIES = {
  homepod: ['listen', 'speak'],
  mac: ['show', 'touch', 'listen', 'speak'],
  iphone: ['show', 'touch', 'listen', 'speak'],
  watch: ['show', 'listen', 'speak']
}

export function getAbilities(deviceType) {
  if (!deviceType) return []
  const normalized = deviceType.toLowerCase()
  return DEVICE_ABILITIES[normalized] || []
}

export function isKnownDevice(deviceType) {
  if (!deviceType) return false
  const normalized = String(deviceType).toLowerCase()
  return normalized in DEVICE_ABILITIES
}
