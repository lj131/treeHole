/**
 * 聊天页朗读：设置持久化 + 给 TTS 用的文本清洗。
 *
 * **清洗是必要的**：角色回复是 Markdown，直接丢给 TTS 会念出"星号""井号"，
 * 链接会念出一长串 URL，代码块会把变量名一个个念出来。
 */

/**
 * 单次合成的文本上限。
 * **必须与后端 `funcation/voice_pack.MAX_SYNTH_CHARS` 保持一致** ——
 * 前端先截断是为了避免让用户等一次注定被拒的请求；后端再兜一次做安全边界。
 */
export const MAX_SYNTH_CHARS = 600

const READ_ALOUD_KEY = 'chat_read_aloud_enabled'

/** 表情符号（常见符号区 + 补充平面）—— TTS 念不出来，只会变成怪停顿 */
const EMOJI_RE =
  /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}]/gu

/**
 * 把 Markdown 回复清洗成适合朗读的纯文本。
 *
 * 顺序有讲究：代码块 → 行内代码 → 图片 → 链接 → 块级标记 → 强调 → 收尾残留。
 * 反过来的话，链接里的 `_` 会被当成强调符号先吃掉一半。
 */
export function cleanTextForSpeech(raw: string): string {
  if (!raw) return ''
  let text = raw

  // 代码块整段不念（念代码没有意义），行内代码只去反引号、保留内容
  text = text.replace(/```[\s\S]*?```/g, ' ')
  text = text.replace(/`([^`]*)`/g, '$1')

  // 图片整段不念；链接只保留可读文字
  text = text.replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
  text = text.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')

  // 块级标记：标题 / 引用 / 无序列表 / 有序列表 / 分隔线
  text = text.replace(/^\s{0,3}#{1,6}\s*/gm, '')
  text = text.replace(/^\s{0,3}>\s?/gm, '')
  text = text.replace(/^\s{0,3}[-*+]\s+/gm, '')
  text = text.replace(/^\s{0,3}\d+\.\s+/gm, '')
  text = text.replace(/^\s{0,3}([-*_]\s*){3,}$/gm, ' ')

  // 强调：先粗体（含斜体嵌套）再斜体，最后删除线
  text = text.replace(/(\*\*\*|___)(.*?)\1/g, '$2')
  text = text.replace(/(\*\*|__)(.*?)\1/g, '$2')
  text = text.replace(/(\*|_)(.*?)\1/g, '$2')
  text = text.replace(/~~(.*?)~~/g, '$1')

  // 收尾：清掉没配对成功的残留标记（例如单独一行 "***"）。
  // 连续 2 个以上的 * _ ~ ` 在正常中文行文里不会出现，删掉是安全的。
  text = text.replace(/[*_~`]{2,}/g, ' ')

  // 表情不念
  text = text.replace(EMOJI_RE, '')

  // 空白归一
  return text.replace(/\s+/g, ' ').trim()
}

/**
 * 按上限截断，尽量在句末收尾 —— 半句话听起来像被打断。
 */
export function truncateForSpeech(text: string, limit: number = MAX_SYNTH_CHARS): string {
  if (text.length <= limit) return text
  const head = text.slice(0, limit)
  const lastStop = Math.max(
    head.lastIndexOf('。'),
    head.lastIndexOf('！'),
    head.lastIndexOf('？'),
    head.lastIndexOf('.'),
    head.lastIndexOf('!'),
    head.lastIndexOf('?'),
  )
  return lastStop > 0 ? head.slice(0, lastStop + 1) : head
}

export function isReadAloudEnabled(): boolean {
  try {
    return localStorage.getItem(READ_ALOUD_KEY) === 'true'
  } catch {
    return false // localStorage 不可用（隐私模式）→ 退回默认关闭
  }
}

export function setReadAloudEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(READ_ALOUD_KEY, String(enabled))
  } catch {
    /* localStorage 不可用，忽略 */
  }
}
