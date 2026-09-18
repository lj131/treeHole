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

describe('CharacterPortrait3D 表情驱动优先级', () => {
  type Vm = { currentExpression: () => { expression: string; source: string } }

  it('心情优先于好感度', () => {
    const w = mount(CharacterPortrait3D, {
      props: { characterId: 'linwan', mood: '生气', favorability: 95 },
    })
    const r = (w.vm as unknown as Vm).currentExpression()
    expect(r.expression).toBe('angry')
    expect(r.source).toBe('mood')
  })

  it('心情未知 → 用好感度', () => {
    const w = mount(CharacterPortrait3D, {
      props: { characterId: 'linwan', mood: '暴走', favorability: 80 },
    })
    const r = (w.vm as unknown as Vm).currentExpression()
    expect(r.expression).toBe('happy')
    expect(r.source).toBe('favorability')
  })

  it('两者都缺 → 用模型配置的默认表情', () => {
    const modelConfig: Model3DConfig = {
      url: '/models/a.vrm',
      format: 'vrm',
      default_expression: 'surprised',
    }
    const w = mount(CharacterPortrait3D, { props: { characterId: 'linwan', modelConfig } })
    const r = (w.vm as unknown as Vm).currentExpression()
    expect(r.expression).toBe('surprised')
    expect(r.source).toBe('default')
  })

  it('心情变化会实时反映到表情（响应式）', async () => {
    const w = mount(CharacterPortrait3D, { props: { characterId: 'linwan', mood: '平静' } })
    const vm = w.vm as unknown as Vm
    expect(vm.currentExpression().expression).toBe('relaxed')
    await w.setProps({ mood: '难过' })
    expect(vm.currentExpression().expression).toBe('sad')
  })
})

/**
 * 无框浮出（pop-out）只应该在 3D 真正渲染时生效。
 * jsdom 没有 WebGL → 走静态降级路径，正好用来钉住"降级不能被浮出布局搞坏"。
 */
describe('CharacterPortrait3D 无框浮出与降级共存', () => {
  it('浮出开启但 WebGL 不可用 → 仍然是静态头像，且不挂 is-popout', () => {
    const w = mount(CharacterPortrait3D, {
      props: { characterId: 'linwan', characterName: '林婉', popOut: true },
    })
    expect(w.find('.static-portrait').exists()).toBe(true)
    expect(w.classes()).not.toContain('is-popout')
    expect(w.find('.portrait-stage').exists()).toBe(false)
  })

  it('显式关闭浮出时同样正常降级', () => {
    const w = mount(CharacterPortrait3D, {
      props: { characterId: 'linwan', characterName: '林婉', popOut: false },
    })
    expect(w.find('.static-portrait').exists()).toBe(true)
    expect(w.classes()).not.toContain('is-popout')
  })
})
