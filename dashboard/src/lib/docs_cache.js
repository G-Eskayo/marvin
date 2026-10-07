// What the Docs tab keeps after docs:repos or docs:refresh: { generated_at, repos: [...] }, with repos
// always an array so the project list can render even when the main process answers oddly.
export function docsCacheFrom(result) {
  if (Array.isArray(result)) return { generated_at: null, repos: result }
  const repos = Array.isArray(result?.repos) ? result.repos : []
  return { generated_at: result?.generated_at ?? null, repos }
}
