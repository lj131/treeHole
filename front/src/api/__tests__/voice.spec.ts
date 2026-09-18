import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

/**
 * voice.ts 直接用 fetch（不走 @/api/request），因为它要传 FormData 和收 Blob，
 * 共享 helper 强制 application/json 且只认 JSON 响应。所以这里 stub 全局 fetch。
 */
import {
  getVoiceOptions,
  getVoicePacks,
  createVoicePack,
  updateVoicePack,
  deleteVoicePack,
  uploadVoiceReference,
  deleteVoiceReference,
  previewVoice,
  bindVoicePack,
} from '@/api/voice'

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
    blob: async () => new Blob(['audio']),
  } as unknown as Response
}

const fetchMock = vi.fn()

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
  localStorage.setItem('auth_token', 'test-token')
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

/** 取最近一次 fetch 的 (url, init) */
function lastCall(): [string, RequestInit] {
  // 不用 Array.prototype.at：构建时的 type-check 目标 lib 还没到 es2022
  const calls = fetchMock.mock.calls
  const call = calls[calls.length - 1]!
  return [call[0] as string, (call[1] || {}) as RequestInit]
}

describe('voice API 客户端', () => {
  it('带上 Authorization 头', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ packs: [], bindings: [], max_packs: 30 }))
    await getVoicePacks()
    const [, init] = lastCall()
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer test-token')
  })

  it('GET 路径正确', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ voices: [], engines: [] }))
    await getVoiceOptions()
    expect(lastCall()[0]).toContain('/voice/voices')
  })

  it('创建语音包发 POST + JSON body', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ message: 'ok', pack: { id: 'vp_1' } }))
    await createVoicePack({ name: '温柔', speaking_rate: 0.9 })
    const [url, init] = lastCall()
    expect(url).toContain('/voice/packs')
    expect(init.method).toBe('POST')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
    expect(JSON.parse(init.body as string)).toEqual({ name: '温柔', speaking_rate: 0.9 })
  })

  it('更新语音包用 PATCH', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ message: 'ok', pack: {} }))
    await updateVoicePack('vp_1', { pitch: 2 })
    const [url, init] = lastCall()
    expect(url).toContain('/voice/packs/vp_1')
    expect(init.method).toBe('PATCH')
  })

  it('删除语音包用 DELETE', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ message: 'ok' }))
    await deleteVoicePack('vp_1')
    expect(lastCall()[1].method).toBe('DELETE')
  })

  it('pack_id 做 URL 编码', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ message: 'ok' }))
    await deleteVoicePack('vp_1/../evil')
    expect(lastCall()[0]).toContain(encodeURIComponent('vp_1/../evil'))
  })

  // ---------- 上传 ----------

  it('上传参考音频用 FormData，且不手写 Content-Type', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ message: 'ok', pack: {}, size_kb: 12 }))
    const file = new File(['RIFF'], 'sample.wav', { type: 'audio/wav' })
    await uploadVoiceReference('vp_1', file)

    const [url, init] = lastCall()
    expect(url).toContain('/voice/packs/vp_1/reference')
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
    // 手写 Content-Type 会丢掉 multipart 的 boundary，后端直接解析失败
    expect((init.headers as Record<string, string>)['Content-Type']).toBeUndefined()
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer test-token')
  })

  it('上传时把文件塞进 file 字段', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ message: 'ok', pack: {}, size_kb: 1 }))
    const file = new File(['x'], 'a.mp3', { type: 'audio/mpeg' })
    await uploadVoiceReference('vp_1', file)
    const form = lastCall()[1].body as FormData
    expect((form.get('file') as File).name).toBe('a.mp3')
  })

  it('删除参考音频用 DELETE', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ message: 'ok', pack: {} }))
    await deleteVoiceReference('vp_1')
    const [url, init] = lastCall()
    expect(url).toContain('/voice/packs/vp_1/reference')
    expect(init.method).toBe('DELETE')
  })

  // ---------- 试听 ----------

  it('试听返回 Blob', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}, 200))
    const blob = await previewVoice({ pack_id: 'vp_1' })
    expect(blob).toBeInstanceOf(Blob)
    expect(lastCall()[0]).toContain('/voice/preview')
  })

  it('试听可以只传即时参数（新建时听还没保存的配置）', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}, 200))
    await previewVoice({ voice_name: 'zh-CN-YunxiNeural', speaking_rate: 0.8 })
    const body = JSON.parse(lastCall()[1].body as string)
    expect(body.pack_id).toBeUndefined()
    expect(body.voice_name).toBe('zh-CN-YunxiNeural')
  })

  // ---------- 绑定 ----------

  it('绑定角色发 character_id + pack_id', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ message: 'ok', character_id: 'linwan' }))
    await bindVoicePack('linwan', 'vp_1')
    const body = JSON.parse(lastCall()[1].body as string)
    expect(body).toEqual({ character_id: 'linwan', pack_id: 'vp_1' })
  })

  it('解绑发 pack_id=null（而不是省略字段）', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ message: 'ok', character_id: 'linwan' }))
    await bindVoicePack('linwan', null)
    const body = JSON.parse(lastCall()[1].body as string)
    expect(body.character_id).toBe('linwan')
    expect(body.pack_id).toBeNull()
    // 省略字段后端会当成"没传"，解绑就失效了
    expect('pack_id' in body).toBe(true)
  })

  // ---------- 错误处理 ----------

  it('把后端的 detail 提成可读错误', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: '音色名不合法：xxx' }, 400))
    await expect(createVoicePack({ name: 'x' })).rejects.toThrow('音色名不合法：xxx')
  })

  it('引擎不可用（503）能读到原因', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: '克隆引擎尚未部署' }, 503))
    await expect(previewVoice({ pack_id: 'vp_1' })).rejects.toThrow('克隆引擎尚未部署')
  })

  it('响应不是 JSON 时退回状态码文案，不抛解析错误', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error('not json')
      },
    } as unknown as Response)
    await expect(getVoicePacks()).rejects.toThrow(/502/)
  })

  it('非管理员被拒（403）时给出可读信息', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: '仅管理员可操作' }, 403))
    await expect(getVoicePacks()).rejects.toThrow('仅管理员可操作')
  })
})
