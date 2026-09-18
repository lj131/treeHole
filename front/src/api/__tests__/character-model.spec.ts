import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('@/api/request', () => ({
  request: vi.fn(),
}))

import { request } from '@/api/request'
import {
  getCharacterModel,
  updateCharacterModelConfig,
  deleteCharacterModel,
  uploadCharacterModel,
} from '@/api/character'
import type { Model3DConfig } from '@/types/api'

const model: Model3DConfig = { url: '/models/linwan_a1.vrm', format: 'vrm', scale: 1 }

describe('character 3D model API client', () => {
  beforeEach(() => vi.clearAllMocks())
  afterEach(() => vi.unstubAllGlobals())

  it('getCharacterModel 带 character_id 查询参数', async () => {
    vi.mocked(request).mockResolvedValue({
      character_id: 'linwan',
      model3d: null,
      supported_expressions: [],
      max_size_mb: 64,
    })
    await getCharacterModel('linwan')
    expect(request).toHaveBeenCalledWith('/character/model?character_id=linwan')
  })

  it('getCharacterModel 不传 id 时无查询串', async () => {
    vi.mocked(request).mockResolvedValue({
      character_id: 'linwan',
      model3d: null,
      supported_expressions: [],
      max_size_mb: 64,
    })
    await getCharacterModel()
    expect(request).toHaveBeenCalledWith('/character/model')
  })

  it('character_id 做 URL 编码', async () => {
    vi.mocked(request).mockResolvedValue({
      character_id: 'a b',
      model3d: null,
      supported_expressions: [],
      max_size_mb: 64,
    })
    await getCharacterModel('a b')
    expect(request).toHaveBeenCalledWith('/character/model?character_id=a%20b')
  })

  it('updateCharacterModelConfig 只发 patch 字段', async () => {
    vi.mocked(request).mockResolvedValue({ message: 'ok', model3d: model })
    const res = await updateCharacterModelConfig({ scale: 1.4 }, 'linwan')
    expect(request).toHaveBeenCalledWith('/character/model/config?character_id=linwan', {
      method: 'POST',
      body: JSON.stringify({ scale: 1.4 }),
    })
    expect(res.model3d).toEqual(model)
  })

  it('updateCharacterModelConfig 把后端 error 转成异常', async () => {
    vi.mocked(request).mockResolvedValue({ error: '角色尚未配置 3D 模型' })
    await expect(updateCharacterModelConfig({ scale: 2 }, 'linwan')).rejects.toThrow(
      '角色尚未配置 3D 模型',
    )
  })

  it('deleteCharacterModel 发 DELETE', async () => {
    vi.mocked(request).mockResolvedValue({ message: '已移除 3D 模型', model3d: null })
    await deleteCharacterModel('linwan')
    expect(request).toHaveBeenCalledWith('/character/model?character_id=linwan', {
      method: 'DELETE',
    })
  })

  // ---------- 上传（走裸 fetch + FormData） ----------

  function stubFetch(ok: boolean, body: unknown) {
    const fetchMock = vi.fn().mockResolvedValue({
      ok,
      json: async () => body,
    })
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  it('uploadCharacterModel 用 multipart 且不带 JSON Content-Type', async () => {
    const fetchMock = stubFetch(true, { message: '模型上传成功', model3d: model })
    const file = new File([new Uint8Array([1, 2, 3])], 'a.vrm', { type: 'application/octet-stream' })

    const res = await uploadCharacterModel(file, 'linwan')

    expect(res.model3d).toEqual(model)
    const [url, init] = fetchMock.mock.calls[0]!
    expect(String(url)).toContain('/character/model?character_id=linwan')
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
    expect((init.headers as Record<string, string>)['Content-Type']).toBeUndefined()
    expect((init.body as FormData).get('file')).toBe(file)
  })

  it('uploadCharacterModel 把业务 error 抛成异常', async () => {
    stubFetch(true, { error: '不支持的模型格式: .exe，仅支持 glb/gltf/vrm' })
    const file = new File(['x'], 'bad.exe')
    await expect(uploadCharacterModel(file, 'linwan')).rejects.toThrow('不支持的模型格式')
  })

  it('uploadCharacterModel 在 HTTP 失败时抛错', async () => {
    stubFetch(false, { detail: '无权访问该角色' })
    const file = new File(['x'], 'a.vrm')
    await expect(uploadCharacterModel(file, 'linwan')).rejects.toThrow('无权访问该角色')
  })
})
