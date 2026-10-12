/**
 * LipSyncEngine 测试
 * TDD: 先写测试，观看失败，再实现最小代码
 */

import { describe, it, expect, beforeEach, afterEach, vi, type Mock } from 'vitest';
import { LipSyncEngine } from './LipSyncEngine';

/**
 * mock 的 AnalyserNode / SourceNode —— 只声明引擎实际会调用的成员。
 *
 * 不用 `any`：那样会同时触发 `no-explicit-any`，而且丢掉拼写检查
 * （引擎改了成员名，这里不会报错）。
 */
interface MockAnalyser {
  fftSize: number;
  smoothingTimeConstant: number;
  frequencyBinCount: number;
  getByteFrequencyData: Mock<() => void>;
  connect: Mock<() => void>;
  disconnect: Mock<() => void>;
}

interface MockSource {
  connect: Mock<() => void>;
  disconnect: Mock<() => void>;
  constructor: { name: string };
}

interface MockAudioContextInstance {
  resume: Mock<() => Promise<void>>;
  close: Mock<() => Promise<void>>;
  createAnalyser: Mock<() => MockAnalyser>;
  createMediaElementSource: Mock<() => MockSource>;
}

describe('LipSyncEngine', () => {
  let engine: LipSyncEngine;
  let mockAudioContextInstance: MockAudioContextInstance;
  let originalAudioContext: typeof globalThis.AudioContext;

  beforeEach(() => {
    // 保存原始 AudioContext
    originalAudioContext = globalThis.AudioContext;

    // Mock AudioContext 实例
    mockAudioContextInstance = {
      resume: vi.fn<() => Promise<void>>(() => Promise.resolve()),
      close: vi.fn<() => Promise<void>>(() => Promise.resolve()),
      createAnalyser: vi.fn<() => MockAnalyser>(() => ({
        fftSize: 256,
        smoothingTimeConstant: 0.3,
        frequencyBinCount: 128,
        getByteFrequencyData: vi.fn<() => void>(),
        connect: vi.fn<() => void>(),
        disconnect: vi.fn<() => void>(),
      })),
      createMediaElementSource: vi.fn<() => MockSource>(() => ({
        connect: vi.fn<() => void>(),
        disconnect: vi.fn<() => void>(),
        constructor: { name: 'MediaElementAudioSourceNode' },
      })),
    };

    // Mock AudioContext 类
    class MockAudioContext {
      constructor() {
        Object.assign(this, mockAudioContextInstance);
      }
      resume = mockAudioContextInstance.resume;
      close = mockAudioContextInstance.close;
      createAnalyser = mockAudioContextInstance.createAnalyser;
      createMediaElementSource = mockAudioContextInstance.createMediaElementSource;
    }

    // 用断言而不是 @ts-ignore —— 断言是显式的，且不会顺手压掉旁边真实存在的错误
    globalThis.AudioContext = MockAudioContext as unknown as typeof AudioContext;

    // 在 mock 设置之后创建 engine
    engine = new LipSyncEngine();
  });

  afterEach(() => {
    engine.dispose();
    // 恢复原始 AudioContext
    globalThis.AudioContext = originalAudioContext;
  });

  describe('音频元素分析', () => {
    it('首次调用创建 MediaElementSource', () => {
      const audioEl = document.createElement('audio');
      const mockCallback = vi.fn<(intensity: number) => void>();

      engine.startElementAnalysis(audioEl, mockCallback);

      expect(mockAudioContextInstance.createMediaElementSource).toHaveBeenCalledWith(audioEl);
    });

    it('重复调用同一元素复用 MediaElementSource', () => {
      const audioEl = document.createElement('audio');
      const mockCallback = vi.fn<(intensity: number) => void>();

      engine.startElementAnalysis(audioEl, mockCallback);
      engine.startElementAnalysis(audioEl, mockCallback);

      expect(mockAudioContextInstance.createMediaElementSource).toHaveBeenCalledTimes(1);
    });
  });

  describe('停止分析', () => {
    it('停止时发送强度 0', () => {
      const audioEl = document.createElement('audio');
      const mockCallback = vi.fn<(intensity: number) => void>();

      engine.startElementAnalysis(audioEl, mockCallback);
      engine.stop(true);

      expect(mockCallback).toHaveBeenCalledWith(0);
    });
  });
});
