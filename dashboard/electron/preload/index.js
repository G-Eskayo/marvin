import { contextBridge, ipcRenderer } from 'electron'

// Expose a safe, read-only API to the renderer via window.api. Deliberately
// no write methods -- this dashboard is a viewer onto metrics_registry.py's
// data (G-Eskayo/marvin#2), which owns writing.
contextBridge.exposeInMainWorld('api', {
  metrics: {
    index: () => ipcRenderer.invoke('metrics:index'),
    subsystems: () => ipcRenderer.invoke('metrics:subsystems'),
    history: (subsystem) => ipcRenderer.invoke('metrics:history', subsystem)
  }
})
