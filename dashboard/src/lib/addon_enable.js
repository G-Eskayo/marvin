export async function enableAddon(name, api) {
  try {
    await api.setFeature(name, true)
  } catch (e) {
    return { features: null, error: e?.message || String(e) }
  }
  try {
    const features = await api.features()
    return { features, error: null }
  } catch (e) {
    return { features: null, error: e?.message || String(e) }
  }
}
