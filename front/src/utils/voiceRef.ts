/**
 * 参考音频上传结果 → 界面提示文案。
 *
 * 抽成纯函数是为了能单测：这段有真实的分支逻辑
 * （有警告 / 有时长 / 都没有），而 SettingsView 挂载成本很高。
 */

export interface RefUploadResult {
  size_kb: number
  /** null = 读不出时长（非 WAV / 文件损坏），**不等于"没问题"** */
  duration_seconds: number | null
  /** null = 没毛病 */
  warning: string | null
}

export interface RefUploadNotice {
  text: string
  /** false → 用警告样式（黄/红）。音频太短仍算"上传成功但要注意" */
  ok: boolean
}

export function describeRefUpload(res: RefUploadResult): RefUploadNotice {
  // 警告优先级最高：用户必须知道"这个样本可能克隆不好"，
  // 否则他只会觉得克隆质量差，而不知道是自己音频的问题。
  if (res.warning) {
    return { text: `参考音频已上传，但 ${res.warning}`, ok: false }
  }

  // 只有真的读出了时长才显示秒数 —— 读不出来时别编一个
  const dur = typeof res.duration_seconds === 'number'
    ? `，${res.duration_seconds.toFixed(1)} 秒`
    : ''
  return {
    text: `参考音频已上传（${res.size_kb} KB${dur}）。建议点「试听」确认克隆效果。`,
    ok: true,
  }
}
