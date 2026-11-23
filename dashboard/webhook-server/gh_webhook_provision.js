// Idempotent GitHub webhook provisioning: list, create, or patch webhooks on target repos
export async function ensureWebhooks({ repos = [], url = '', secret = '', exec = null }) {
  if (!exec || !url || !secret || !repos.length) {
    throw new Error('ensureWebhooks requires exec, url, secret, and repos')
  }

  const target = url.replace(/\/$/, '')
  const events = ['push', 'pull_request', 'pull_request_review']
  const contentType = 'json'
  const insecure = false

  for (const repo of repos) {
    try {
      // List existing webhooks
      const listCmd = ['api', `repos/${repo}/hooks`, '--paginate', '--jq', '.[] | {id, url: .config.url}']
      const listOutput = await exec(listCmd)
      const existing = listOutput.trim() ? listOutput.split('\n').map(line => {
        try { return JSON.parse(line) } catch { return null }
      }).filter(Boolean) : []

      // Check if webhook already exists for this URL
      const hook = existing.find(h => h.url === target)

      if (hook) {
        // Patch existing hook to ensure events are correct
        const patchCmd = [
          'api', `repos/${repo}/hooks/${hook.id}`,
          '-X', 'PATCH',
          '-f', 'active=true'
        ]
        // Add events as an array (gh syntax: -f events[]=push -f events[]=...)
        for (const event of events) {
          patchCmd.push('-f', `events[]=${event}`)
        }
        // Update config fields including the secret
        patchCmd.push('-f', `config[url]=${target}`)
        patchCmd.push('-f', `config[content_type]=${contentType}`)
        patchCmd.push('-f', `config[secret]=${secret}`)
        patchCmd.push('-f', `config[insecure_ssl]=${insecure}`)
        await exec(patchCmd)
        console.log(`[webhook-provision] patched ${repo} (hook ${hook.id})`)
      } else {
        // Create new webhook
        const createCmd = [
          'api', `repos/${repo}/hooks`,
          '-X', 'POST',
          '-f', 'active=true'
        ]
        // Add events as an array (gh syntax: -f events[]=push -f events[]=...)
        for (const event of events) {
          createCmd.push('-f', `events[]=${event}`)
        }
        // Set config fields (nested under config key)
        createCmd.push('-f', `config[url]=${target}`)
        createCmd.push('-f', `config[content_type]=${contentType}`)
        createCmd.push('-f', `config[secret]=${secret}`)
        createCmd.push('-f', `config[insecure_ssl]=${insecure}`)
        await exec(createCmd)
        console.log(`[webhook-provision] created ${repo}`)
      }
    } catch (err) {
      console.error(`[webhook-provision] failed on ${repo}: ${String(err?.message || err).slice(0, 100)}`)
      // Continue processing other repos; one failure doesn't block the batch
    }
  }
}
