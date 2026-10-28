// Map of known voice devices and their capabilities
export const DEVICE_ABILITIES = {
  homepod: {
    name: 'HomePod',
    capabilities: ['tts', 'streaming', 'interrupts'],
    minVersion: '16.0'
  },
  mac: {
    name: 'Mac',
    capabilities: ['tts', 'streaming', 'interrupts'],
    minVersion: '10.14'
  },
  iphone: {
    name: 'iPhone',
    capabilities: ['tts', 'streaming', 'interrupts'],
    minVersion: '14.0'
  },
  watch: {
    name: 'Apple Watch',
    capabilities: ['tts', 'streaming'],
    minVersion: '6.0'
  }
}

// Check if a device is recognized
export function isKnownDevice(device) {
  if (!device || typeof device !== 'string') {
    return false
  }

  return device.toLowerCase() in DEVICE_ABILITIES
}
