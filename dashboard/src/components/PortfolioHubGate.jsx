import { useEffect, useState } from 'react'
import PortfolioHub from './PortfolioHub.jsx'
import { AddonNotSetUp } from './AddonNotSetUp.jsx'

export default function PortfolioHubGate() {
  const [features, setFeatures] = useState(null)
  const [loading, setLoading] = useState(true)

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
        onEnable={async (name) => {
          try {
            await window.api.instance.setFeature(name, true)
            // Refresh features after enabling
            const f = await window.api.instance.features()
            setFeatures(f)
          } catch (e) {
            console.error('Failed to enable feature:', e)
          }
        }}
      />
    )
  }

  return <PortfolioHub />
}
