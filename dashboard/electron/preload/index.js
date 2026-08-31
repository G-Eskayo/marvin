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
  }
})
