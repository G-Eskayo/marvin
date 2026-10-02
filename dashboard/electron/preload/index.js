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
    deny: (payload) => ipcRenderer.invoke('mr:deny', payload),
    ticketContext: (ticketRef) => ipcRenderer.invoke('mr:ticketContext', ticketRef),
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
  health: {
    status: () => ipcRenderer.invoke('health:status'),
    refresh: () => ipcRenderer.invoke('health:refresh')
  },
  docs: {
    repos: () => ipcRenderer.invoke('docs:repos'),
    refresh: () => ipcRenderer.invoke('docs:refresh'),
    tree: (repo) => ipcRenderer.invoke('docs:tree', repo),
    content: (repo, path) => ipcRenderer.invoke('docs:content', repo, path)
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
    imagePreview: (slug) => ipcRenderer.invoke('portfolio:image:preview', slug),
    inventory: () => ipcRenderer.invoke('portfolio:inventory'),
    inventoryImage: (rel) => ipcRenderer.invoke('portfolio:inventory:image', rel),
    refreshInventory: () => ipcRenderer.invoke('portfolio:inventory:refresh'),
    pageMarkup: (slug) => ipcRenderer.invoke('portfolio:page-markup', slug),
    templates: () => ipcRenderer.invoke('portfolio:templates'),
    templateSource: (id) => ipcRenderer.invoke('portfolio:template:source', id),
    saveTemplateSource: (id, content) => ipcRenderer.invoke('portfolio:template:source:save', id, content),
    renderTemplate: (id, data, options) => ipcRenderer.invoke('portfolio:template:render', id, data, options),
    planProject: (data) => ipcRenderer.invoke('portfolio:project:plan', data),
    reference: () => ipcRenderer.invoke('portfolio:reference'),
    referenceMarkup: (slug) => ipcRenderer.invoke('portfolio:reference:markup', slug)
  },
  activity: {
    list: () => ipcRenderer.invoke('activity:list'),
    timeline: (number) => ipcRenderer.invoke('activity:timeline', number)
  }
})
