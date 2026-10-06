import { contextBridge, ipcRenderer } from 'electron'

// Expose a safe, read-only API to the renderer via window.api. Deliberately
// no write methods -- this dashboard is a viewer onto metrics_registry.py's
// data (G-Eskayo/marvin#2), which owns writing.
contextBridge.exposeInMainWorld('api', {
  metrics: {
    index: () => ipcRenderer.invoke('metrics:index'),
    subsystems: () => ipcRenderer.invoke('metrics:subsystems'),
    history: (subsystem) => ipcRenderer.invoke('metrics:history', subsystem)
  },
  mr: {
    list: () => ipcRenderer.invoke('mr:list'),
    // Confirmation happens in the main process via a native dialog, not here --
    // see the comment on the mr:approve handler for why.
    approve: (pr) => ipcRenderer.invoke('mr:approve', pr),
    mergeState: (url) => ipcRenderer.invoke('mr:mergeState', url),
    clearSentBack: (url) => ipcRenderer.invoke('mr:clearSentBack', url),
    deny: (payload) => ipcRenderer.invoke('mr:deny', payload),
    ticketContext: (ticketRef, repo) => ipcRenderer.invoke('mr:ticketContext', ticketRef, repo),
    parity: () => ipcRenderer.invoke('mr:parity'),
    reviewStatus: () => ipcRenderer.invoke('mr:reviewStatus'),
    markSeen: (prNumbers) => ipcRenderer.invoke('mr:markSeen', prNumbers),
    // Fires whenever the webhook-server's /mr-ready ping reaches this
    // machine's own refresh_server.js. Returns an unsubscribe function.
    onRefresh: (callback) => {
      const listener = () => callback()
      ipcRenderer.on('mr:refresh', listener)
      return () => ipcRenderer.removeListener('mr:refresh', listener)
    }
  },
  dispatch: {
    status: () => ipcRenderer.invoke('dispatch:status')
  },
  devices: {
    status: () => ipcRenderer.invoke('devices:status')
  },
  profiles: {
    list: () => ipcRenderer.invoke('profiles:list'),
    setDispatch: (repo, value) => ipcRenderer.invoke('profiles:setDispatch', repo, value),
    selftest: (repo) => ipcRenderer.invoke('profiles:selftest', repo)
  },
  working: {
    now: () => ipcRenderer.invoke('working:now')
  },
  health: {
    status: () => ipcRenderer.invoke('health:status'),
    agents: () => ipcRenderer.invoke('health:agents'),
    ticketAgents: () => ipcRenderer.invoke('health:ticketAgents'),
    tools: () => ipcRenderer.invoke('health:tools'),
    refresh: () => ipcRenderer.invoke('health:refresh')
  },
  docs: {
    repos: () => ipcRenderer.invoke('docs:repos'),
    refresh: () => ipcRenderer.invoke('docs:refresh'),
    tree: (repo) => ipcRenderer.invoke('docs:tree', repo),
    content: (repo, path) => ipcRenderer.invoke('docs:content', repo, path),
    search: (query, opts) => ipcRenderer.invoke('docs:search', query, opts),
    files: (query) => ipcRenderer.invoke('docs:files', query),
    reveal: (filePath) => ipcRenderer.invoke('docs:reveal', filePath)
  },
  portfolio: {
    components: () => ipcRenderer.invoke('portfolio:components'),
    saveComponent: (name, html, notes) => ipcRenderer.invoke('portfolio:component:save', name, html, notes),
    createComponent: (name, html, notes) => ipcRenderer.invoke('portfolio:component:create', name, html, notes),
    previewHead: () => ipcRenderer.invoke('portfolio:preview-head'),
    rules: () => ipcRenderer.invoke('portfolio:rules'),
    saveRules: (overrides) => ipcRenderer.invoke('portfolio:rules:save', overrides),
    guide: () => ipcRenderer.invoke('portfolio:guide'),
    saveGuide: (text) => ipcRenderer.invoke('portfolio:guide:save', text),
    latestEval: () => ipcRenderer.invoke('portfolio:eval:latest'),
    runEval: () => ipcRenderer.invoke('portfolio:eval:run'),
    images: () => ipcRenderer.invoke('portfolio:images'),
    generateImage: (slug) => ipcRenderer.invoke('portfolio:image:generate', slug),
    imageMotifs: () => ipcRenderer.invoke('portfolio:image:motifs'),
    imageVariants: (slug) => ipcRenderer.invoke('portfolio:image:variants', slug),
    newImageVariant: (slug, motif) => ipcRenderer.invoke('portfolio:image:variant:new', slug, motif),
    chooseImageVariant: (slug, motif, salt) => ipcRenderer.invoke('portfolio:image:variant:choose', slug, motif, salt),
    addProject: (spec, opts) => ipcRenderer.invoke('portfolio:project:add', spec, opts),
    pipelineStatus: () => ipcRenderer.invoke('portfolio:pipeline:status'),
    runPipeline: () => ipcRenderer.invoke('portfolio:pipeline:run'),
    elements: () => ipcRenderer.invoke('portfolio:elements'),
    verifyElement: (id) => ipcRenderer.invoke('portfolio:element:verify', id),
    applyImages: () => ipcRenderer.invoke('portfolio:images:apply'),
    deleteImageVariant: (slug, motif, salt) => ipcRenderer.invoke('portfolio:image:variant:delete', slug, motif, salt),
    variantPreview: (slug, motif, salt) => ipcRenderer.invoke('portfolio:image:variant:preview', slug, motif, salt),
    imagePreview: (slug) => ipcRenderer.invoke('portfolio:image:preview', slug),
    inventory: () => ipcRenderer.invoke('portfolio:inventory'),
    inventoryImage: (rel) => ipcRenderer.invoke('portfolio:inventory:image', rel),
    refreshInventory: () => ipcRenderer.invoke('portfolio:inventory:refresh'),
    chrome: () => ipcRenderer.invoke('portfolio:chrome'),
    pageMarkup: (slug) => ipcRenderer.invoke('portfolio:page-markup', slug),
    templates: () => ipcRenderer.invoke('portfolio:templates'),
    templateSource: (id) => ipcRenderer.invoke('portfolio:template:source', id),
    specimen: (id) => ipcRenderer.invoke('portfolio:template:specimen', id),
    renderTemplate: (id, data, options) => ipcRenderer.invoke('portfolio:template:render', id, data, options),
    planProject: (data) => ipcRenderer.invoke('portfolio:project:plan', data),
    reference: () => ipcRenderer.invoke('portfolio:reference'),
    referenceMarkup: (slug) => ipcRenderer.invoke('portfolio:reference:markup', slug)
  },
  activity: {
    list: () => ipcRenderer.invoke('activity:list'),
    timeline: (number, repo) => ipcRenderer.invoke('activity:timeline', number, repo),
    overview: () => ipcRenderer.invoke('activity:overview')
  },
  triggers: {
    // Fires when something the Activity tab shows has changed (file watch or GitHub ping).
    on: (callback) => {
      const listener = (_event, trigger) => callback(trigger)
      ipcRenderer.on('trigger', listener)
      return () => ipcRenderer.removeListener('trigger', listener)
    }
  },
  relations: {
    ticket: (repo, number) => ipcRenderer.invoke('relations:ticket', repo, number),
    doc: (project, path) => ipcRenderer.invoke('relations:doc', project, path),
    pr: (repo, number) => ipcRenderer.invoke('relations:pr', repo, number),
    context: (project) => ipcRenderer.invoke('relations:context', project)
  },
  boards: {
    list: () => ipcRenderer.invoke('boards:list'),
    load: (repo, source) => ipcRenderer.invoke('boards:load', repo, source),
    ticket: (repo, number) => ipcRenderer.invoke('boards:ticket', repo, number),
    input: (repo, number, body) => ipcRenderer.invoke('boards:input', repo, number, body),
    summary: (repo) => ipcRenderer.invoke('boards:summary', repo),
    completed: (repo) => ipcRenderer.invoke('boards:completed', repo)
  }
})
