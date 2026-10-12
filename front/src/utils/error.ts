/**
 * 统一的错误信息提取。
 *
 * 为什么需要它：`catch (e: any)` 会让 `e.message` 绕过类型检查 —— 但抛出来的东西
 * 未必是 Error（字符串、对象、甚至 `undefined` 都可能），那样 `e.message` 会得到
 * `undefined` 而不是报错，最后变成一句空白的失败提示。
 *
 * 用 `catch (e)` 拿到 `unknown`，再经这里收敛成字符串，既过 lint 也真的更安全。
 */
export function errorMessage(e: unknown, fallback: string): string {
  if (e instanceof Error && e.message) return e.message
  if (typeof e === 'string' && e) return e
  // 后端有时直接抛对象（如 { detail: '...' }）
  if (e && typeof e === 'object' && 'message' in e) {
    const m = (e as { message?: unknown }).message
    if (typeof m === 'string' && m) return m
  }
  return fallback
}
