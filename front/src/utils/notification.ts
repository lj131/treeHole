/**
 * 浏览器通知工具
 * 页面不可见时推送桌面通知
 */

const NOTIFICATION_ENABLED_KEY = 'notification_enabled'

export function isNotificationSupported(): boolean {
  return 'Notification' in window
}

export function getNotificationPermission(): NotificationPermission | 'unsupported' {
  if (!isNotificationSupported()) return 'unsupported'
  return Notification.permission
}

export async function requestNotificationPermission(): Promise<NotificationPermission> {
  if (!isNotificationSupported()) return 'denied'
  return Notification.requestPermission()
}

export function isNotificationEnabled(): boolean {
  return localStorage.getItem(NOTIFICATION_ENABLED_KEY) !== 'false'
}

export function setNotificationEnabled(enabled: boolean): void {
  localStorage.setItem(NOTIFICATION_ENABLED_KEY, String(enabled))
}

/**
 * 发送浏览器通知（仅在页面不可见 + 用户已开启通知时）
 */
export function sendNotification(title: string, body: string): void {
  if (!isNotificationSupported()) return
  if (Notification.permission !== 'granted') return
  if (!isNotificationEnabled()) return
  if (!document.hidden) return // 页面可见时不发通知

  try {
    new Notification(title, {
      body: body.substring(0, 200),
      icon: '/favicon.ico',
      silent: false,
    })
  } catch {
    // 部分浏览器不支持 Notification 构造函数
  }
}
