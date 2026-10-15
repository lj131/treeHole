import { app, BrowserWindow, ipcMain, Menu, nativeImage, screen, Tray } from 'electron'
import path from 'node:path'
import fs from 'node:fs'

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
let tray: Tray | null = null
/** 用户点了托盘「退出」才是真退出；点窗口 × 只是隐藏 */
let quitting = false

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

/** 取托盘图标。找不到文件也不能崩 —— 空 icon 的托盘照样能出菜单。 */
function trayIcon() {
  const candidates = [
    // 打包态：resources 目录外一层（electron-builder 默认布局）
    path.join(process.resourcesPath || '', 'icon.png'),
    // dev：front/ 下的构建产物目录
    path.join(__dirname, '../build/icon.png'),
    path.join(__dirname, '../public/icon.png'),
  ]
  for (const p of candidates) {
    try {
      if (fs.existsSync(p)) return nativeImage.createFromPath(p)
    } catch {
      // 继续试下一个
    }
  }
  return nativeImage.createEmpty()
}

function toggleVisibility() {
  if (!widgetWindow) return
  if (widgetWindow.isVisible()) widgetWindow.hide()
  else {
    widgetWindow.show()
    widgetWindow.focus()
  }
}

function createTray() {
  if (tray) return tray
  tray = new Tray(trayIcon())
  tray.setToolTip('treeHole 桌面挂件')
  // 左键点击 = 显示/隐藏
  tray.on('click', toggleVisibility)
  rebuildTrayMenu()
  return tray
}

/** 重建托盘菜单（置顶的勾选态会变，所以要能重画） */
function rebuildTrayMenu() {
  if (!tray) return
  const onTop = widgetWindow?.isAlwaysOnTop() ?? true
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: '显示 / 隐藏', click: toggleVisibility },
      { type: 'separator' },
      {
        label: '置顶',
        type: 'checkbox',
        checked: onTop,
        click: () => {
          const next = !(widgetWindow?.isAlwaysOnTop() ?? true)
          widgetWindow?.setAlwaysOnTop(next)
          rebuildTrayMenu()
        },
      },
      { type: 'separator' },
      {
        label: '退出',
        click: () => {
          quitting = true
          app.quit()
        },
      },
    ]),
  )
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

  // 点 × = 藏起来（托盘还在），不是退出 —— 否则"系统托盘"没有意义
  widgetWindow.on('close', (event) => {
    if (quitting) return
    event.preventDefault()
    widgetWindow?.hide()
  })

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
  createTray()          // 必须先建托盘，否则关窗后无法再把窗口唤回
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWidgetWindow()
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
  widgetWindow?.focus()
  rebuildTrayMenu()
})

ipcMain.handle('widget:toggle-visibility', () => {
  toggleVisibility()
  rebuildTrayMenu()
})

// ---- 开机自启 ----
// 用 app.setLoginItemSettings，不引 auto-launch 这个 npm 包（少一个依赖）。
// 只写 { openAtLogin }，不要带 args/path —— 那几个字段在不同平台行为不一致。

ipcMain.handle('widget:get-auto-launch', () => {
  const settings = app.getLoginItemSettings()
  return !!settings.openAtLogin
})

ipcMain.handle('widget:set-auto-launch', (_event, enabled: boolean) => {
  app.setLoginItemSettings({ openAtLogin: !!enabled })
  // 返回**系统里的真实值**：写失败（权限/策略）时上层要能看到事实而不是期望
  return !!app.getLoginItemSettings().openAtLogin
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
