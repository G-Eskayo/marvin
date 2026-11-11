import { useEffect, useState } from 'react'
import PortfolioHub from './PortfolioHub.jsx'
import { AddonNotSetUp } from './AddonNotSetUp.jsx'
import { enableAddon } from '../lib/addon_enable.js'

export default function PortfolioHubGate() {
  const [features, setFeatures] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    async function checkFeatures() {
      try {
        const f = await window.api.instance.features()
        setFeatures(f)
      } catch (e) {
        console.error('Failed to fetch instance features:', e)
        setFeatures({})
      } finally {
        setLoading(false)
      }
    }
    checkFeatures()
  }, [])

  if (loading) {
    return <div>Loading...</div>
  }

  if (!features?.portfolio) {
    return (
      <AddonNotSetUp
        addon="portfolio"
        error={error}
        onEnable={async (name) => {
          setError(null)
          const result = await enableAddon(name, window.api.instance)
          if (result.error) {
            setError(result.error)
          } else {
            setFeatures(result.features)
          }
        }}
      />
    )
  }

  return <PortfolioHub />
}
