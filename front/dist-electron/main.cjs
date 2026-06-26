var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
  // If the importer is in node compatibility mode or this is not an ESM
  // file that has been converted to a CommonJS file using a Babel-
  // compatible transform (i.e. "__esModule" has not been set), then set
  // "default" to the CommonJS "module.exports" for node compatibility.
  isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
  mod
));

// electron/main.ts
var import_electron = require("electron");
var import_node_path = __toESM(require("node:path"), 1);
var DEV_SERVER_URL = process.env.VITE_DEV_SERVER_URL || "http://127.0.0.1:5173";
var isDev = !import_electron.app.isPackaged;
var WIDGET_SIZE = {
  compact: { width: 300, height: 240 },
  expanded: { width: 420, height: 560 }
};
var widgetWindow = null;
var dragStartMouse = null;
var dragStartWindow = null;
function getInitialBounds() {
  const display = import_electron.screen.getPrimaryDisplay();
  const { width, height } = WIDGET_SIZE.compact;
  const margin = 24;
  return {
    width,
    height,
    x: display.workArea.x + display.workArea.width - width - margin,
    y: display.workArea.y + display.workArea.height - height - margin
  };
}
function widgetUrl() {
  if (isDev) {
    return `${DEV_SERVER_URL}/#/widget`;
  }
  return `file://${import_node_path.default.join(__dirname, "../dist/index.html")}#/widget`;
}
function createWidgetWindow() {
  const bounds = getInitialBounds();
  widgetWindow = new import_electron.BrowserWindow({
    ...bounds,
    minWidth: 260,
    minHeight: 180,
    frame: false,
    transparent: true,
    hasShadow: true,
    alwaysOnTop: true,
    skipTaskbar: false,
    resizable: false,
    backgroundColor: "#00000000",
    webPreferences: {
      preload: import_node_path.default.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });
  widgetWindow.setMenuBarVisibility(false);
  widgetWindow.loadURL(widgetUrl());
  if (isDev) {
    widgetWindow.webContents.openDevTools({ mode: "detach" });
  }
  widgetWindow.on("closed", () => {
    widgetWindow = null;
  });
}
function resizeWidget(mode) {
  if (!widgetWindow) return;
  const target = WIDGET_SIZE[mode] ?? WIDGET_SIZE.compact;
  const [x, y] = widgetWindow.getPosition();
  widgetWindow.setBounds({ x, y, ...target }, true);
}
import_electron.app.whenReady().then(() => {
  createWidgetWindow();
  import_electron.app.on("activate", () => {
    if (import_electron.BrowserWindow.getAllWindows().length === 0) createWidgetWindow();
  });
});
import_electron.app.on("window-all-closed", () => {
  if (process.platform !== "darwin") import_electron.app.quit();
});
import_electron.ipcMain.handle("widget:set-size", (_event, mode) => {
  resizeWidget(mode);
});
import_electron.ipcMain.handle("widget:toggle-always-on-top", () => {
  if (!widgetWindow) return false;
  const next = !widgetWindow.isAlwaysOnTop();
  widgetWindow.setAlwaysOnTop(next);
  return next;
});
import_electron.ipcMain.handle("widget:hide", () => {
  widgetWindow?.hide();
});
import_electron.ipcMain.handle("widget:show", () => {
  widgetWindow?.show();
});
import_electron.ipcMain.on("widget:drag-start", () => {
  if (!widgetWindow) return;
  dragStartMouse = import_electron.screen.getCursorScreenPoint();
  dragStartWindow = widgetWindow.getPosition();
});
import_electron.ipcMain.on("widget:drag-move", () => {
  if (!widgetWindow || !dragStartMouse || !dragStartWindow) return;
  const current = import_electron.screen.getCursorScreenPoint();
  widgetWindow.setPosition(
    dragStartWindow[0] + current.x - dragStartMouse.x,
    dragStartWindow[1] + current.y - dragStartMouse.y
  );
});
import_electron.ipcMain.on("widget:drag-end", () => {
  dragStartMouse = null;
  dragStartWindow = null;
});
