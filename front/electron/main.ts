import { app, BrowserWindow, ipcMain, screen } from 'electron'
import path from 'node:path'

const DEV_SERVER_URL = process.env.VITE_DEV_SERVER_URL || 'http://127.0.0.1:5173'
const isDev = !app.isPackaged

const WIDGET_SIZE = {
  compact: { width: 300, height: 240 },
  expanded: { width: 420, height: 560 },
}

type WidgetMode = keyof typeof WIDGET_SIZE

let widgetWindow: BrowserWindow | null = null
let dragStartMouse: Electron.Point | null = null
let dragStartWindow: number[] | null = null

function getInitialBounds() {
  const display = screen.getPrimaryDisplay()
  const { width, height } = WIDGET_SIZE.compact
  const margin = 24
  return {
    width,
    height,
    x: display.workArea.x + display.workArea.width - width - margin,
    y: display.workArea.y + display.workArea.height - height - margin,
  }
}

function widgetUrl() {
  if (isDev) {
    return `${DEV_SERVER_URL}/#/widget`
  }
  return `file://${path.join(__dirname, '../dist/index.html')}#/widget`
}

function createWidgetWindow() {
  const bounds = getInitialBounds()
  widgetWindow = new BrowserWindow({
    ...bounds,
    minWidth: 260,
    minHeight: 180,
    frame: false,
    transparent: true,
    hasShadow: true,
    alwaysOnTop: true,
    skipTaskbar: false,
    resizable: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  })

  widgetWindow.setMenuBarVisibility(false)
  widgetWindow.loadURL(widgetUrl())

  if (isDev) {
    widgetWindow.webContents.openDevTools({ mode: 'detach' })
  }

  widgetWindow.on('closed', () => {
    widgetWindow = null
  })
}

function resizeWidget(mode: WidgetMode) {
  if (!widgetWindow) return
  const target = WIDGET_SIZE[mode] ?? WIDGET_SIZE.compact
  const [x, y] = widgetWindow.getPosition()
  widgetWindow.setBounds({ x, y, ...target }, true)
}

app.whenReady().then(() => {
  createWidgetWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWidgetWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

ipcMain.handle('widget:set-size', (_event, mode: WidgetMode) => {
  resizeWidget(mode)
})

ipcMain.handle('widget:toggle-always-on-top', () => {
  if (!widgetWindow) return false
  const next = !widgetWindow.isAlwaysOnTop()
  widgetWindow.setAlwaysOnTop(next)
  return next
})

ipcMain.handle('widget:hide', () => {
  widgetWindow?.hide()
})

ipcMain.handle('widget:show', () => {
  widgetWindow?.show()
})

ipcMain.on('widget:drag-start', () => {
  if (!widgetWindow) return
  dragStartMouse = screen.getCursorScreenPoint()
  dragStartWindow = widgetWindow.getPosition()
})

ipcMain.on('widget:drag-move', () => {
  if (!widgetWindow || !dragStartMouse || !dragStartWindow) return
  const current = screen.getCursorScreenPoint()
  widgetWindow.setPosition(
    dragStartWindow[0] + current.x - dragStartMouse.x,
    dragStartWindow[1] + current.y - dragStartMouse.y,
  )
})

ipcMain.on('widget:drag-end', () => {
  dragStartMouse = null
  dragStartWindow = null
})
