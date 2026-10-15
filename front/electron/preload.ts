import { contextBridge, ipcRenderer } from 'electron'

type WidgetMode = 'compact' | 'expanded'

contextBridge.exposeInMainWorld('widgetApi', {
  setSize: (mode: WidgetMode) => ipcRenderer.invoke('widget:set-size', mode),
  toggleAlwaysOnTop: () => ipcRenderer.invoke('widget:toggle-always-on-top'),
  hide: () => ipcRenderer.invoke('widget:hide'),
  show: () => ipcRenderer.invoke('widget:show'),
  toggleVisibility: () => ipcRenderer.invoke('widget:toggle-visibility'),
  getAutoLaunch: () => ipcRenderer.invoke('widget:get-auto-launch'),
  setAutoLaunch: (enabled: boolean) => ipcRenderer.invoke('widget:set-auto-launch', enabled),
  dragStart: () => ipcRenderer.send('widget:drag-start'),
  dragMove: () => ipcRenderer.send('widget:drag-move'),
  dragEnd: () => ipcRenderer.send('widget:drag-end'),
})
