import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import CharacterPortrait3D from '@/components/3d/CharacterPortrait3D.vue'
import { DEFAULT_VRM_URL } from '@/utils/avatar3d'
import type { Model3DConfig } from '@/types/api'

/**
 * jsdom 没有 WebGL 上下文 → isWebGLAvailable() 返回 false。
 * 这正好覆盖「3D 不可用时必须降级到静态头像」这条关键路径。
 */
describe('CharacterPortrait3D 降级与配置解析', () => {
  it('WebGL 不可用时渲染静态头像，不挂载 VRMAvatar', () => {
    const w = mount(CharacterPortrait3D, {
      props: {
        characterId: 'linwan',
        characterName: '林婉',
        avatar: '/avatars/linwan.jpg',
      },
    })
    expect(w.find('.static-portrait').exists()).toBe(true)
    expect(w.find('.static-img').attributes('src')).toContain('/avatars/linwan.jpg')
  })

  it('无头像时显示名字首字', () => {
    const w = mount(CharacterPortrait3D, {
      props: { characterId: 'x', characterName: '小梅', avatar: '' },
    })
    expect(w.find('.static-initial').text()).toBe('小')
  })

  it('未配置模型 → isFallbackModel 为 true，URL 为内置 demo', () => {
    const w = mount(CharacterPortrait3D, { props: { characterId: 'linwan' } })
    const vm = w.vm as unknown as {
      isFallbackModel: () => boolean
      activeModelUrl: () => string
    }
    expect(vm.isFallbackModel()).toBe(true)
    expect(vm.activeModelUrl()).toBe(DEFAULT_VRM_URL)
  })

  it('配置了 model3d → isFallbackModel 为 false，URL 指向该模型', () => {
    const modelConfig: Model3DConfig = {
      url: '/models/linwan_ab12.vrm',
      format: 'vrm',
      enabled: true,
    }
    const w = mount(CharacterPortrait3D, { props: { characterId: 'linwan', modelConfig } })
    const vm = w.vm as unknown as {
      isFallbackModel: () => boolean
      activeModelUrl: () => string
    }
    expect(vm.isFallbackModel()).toBe(false)
    expect(vm.activeModelUrl()).toContain('/models/linwan_ab12.vrm')
  })

  it('model3d.enabled=false → 回退 demo 模型', () => {
    const modelConfig: Model3DConfig = {
      url: '/models/off.vrm',
      format: 'vrm',
      enabled: false,
    }
    const w = mount(CharacterPortrait3D, { props: { characterId: 'linwan', modelConfig } })
    const vm = w.vm as unknown as { activeModelUrl: () => string }
    expect(vm.activeModelUrl()).toBe(DEFAULT_VRM_URL)
  })
})
