// electron/preload.ts
var import_electron = require("electron");
import_electron.contextBridge.exposeInMainWorld("widgetApi", {
  setSize: (mode) => import_electron.ipcRenderer.invoke("widget:set-size", mode),
  toggleAlwaysOnTop: () => import_electron.ipcRenderer.invoke("widget:toggle-always-on-top"),
  hide: () => import_electron.ipcRenderer.invoke("widget:hide"),
  show: () => import_electron.ipcRenderer.invoke("widget:show"),
  dragStart: () => import_electron.ipcRenderer.send("widget:drag-start"),
  dragMove: () => import_electron.ipcRenderer.send("widget:drag-move"),
  dragEnd: () => import_electron.ipcRenderer.send("widget:drag-end")
});
