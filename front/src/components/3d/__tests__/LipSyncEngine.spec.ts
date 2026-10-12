/**
 * LipSyncEngine 测试（单例 `lipSyncEngine` 视角）。
 *
 * 与同目录外的 `LipSyncEngine.test.ts` 互补：那份用 `new LipSyncEngine()` 测实例行为，
 * 这份测导出单例 + RMS 计算。**两份都保留** —— 它们覆盖的侧面不同。
 */

import { describe, it, expect, beforeEach, afterEach, vi, type Mock } from 'vitest';
import { lipSyncEngine } from '../LipSyncEngine';

/** mock 的 AnalyserNode（只声明引擎实际会调用的成员，避免 any） */
interface MockAnalyser {
  fftSize: number;
  smoothingTimeConstant: number;
  frequencyBinCount: number;
  getByteFrequencyData: Mock<() => void>;
  connect: Mock<() => void>;
}

interface MockSource {
  connect: Mock<() => void>;
  disconnect: Mock<() => void>;
  constructor: { name: string };
}

describe('LipSyncEngine（单例）', () => {
  let mockCreateMediaElementSource: Mock<() => MockSource>;
  let originalAudioContext: typeof globalThis.AudioContext;

  beforeEach(() => {
    // 保存原始 AudioContext
    originalAudioContext = globalThis.AudioContext;

    // Mock AudioContext
    const mockAnalyser: MockAnalyser = {
      fftSize: 256,
      smoothingTimeConstant: 0.3,
      frequencyBinCount: 128,
      getByteFrequencyData: vi.fn<() => void>(),
      connect: vi.fn<() => void>(),
    };

    mockCreateMediaElementSource = vi.fn<() => MockSource>(() => ({
      connect: vi.fn<() => void>(),
      disconnect: vi.fn<() => void>(),
      constructor: { name: 'MediaElementAudioSourceNode' },
    }));

    const mockAudioContextInstance = {
      resume: vi.fn<() => Promise<void>>(() => Promise.resolve()),
      close: vi.fn<() => Promise<void>>(() => Promise.resolve()),
      createAnalyser: vi.fn<() => MockAnalyser>(() => mockAnalyser),
      createMediaElementSource: mockCreateMediaElementSource,
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

    // 用断言而不是 @ts-ignore —— 显式，且不会顺手压掉旁边真实存在的错误
    globalThis.AudioContext = MockAudioContext as unknown as typeof AudioContext;
  });

  afterEach(() => {
    lipSyncEngine.dispose();
    // 恢复原始 AudioContext
    globalThis.AudioContext = originalAudioContext;
  });

  it('静音数据（全 0）的 RMS 为 0', () => {
    const silentData = new Uint8Array(128).fill(0);

    expect(calculateTestRMS(silentData)).toBe(0);
  });

  it('startElementAnalysis 调用 createMediaElementSource', () => {
    const audioEl = document.createElement('audio');

    lipSyncEngine.startElementAnalysis(audioEl, vi.fn<(i: number) => void>());

    expect(mockCreateMediaElementSource).toHaveBeenCalledWith(audioEl);
  });

  it('stop(true) 发送强度 0', () => {
    const audioEl = document.createElement('audio');
    const callback = vi.fn<(i: number) => void>();

    lipSyncEngine.startElementAnalysis(audioEl, callback);
    lipSyncEngine.stop(true);

    expect(callback).toHaveBeenCalledWith(0);
  });
});

/** 测试辅助：按 RMS 公式算强度，用来独立验证引擎的算法 */
function calculateTestRMS(dataArray: Uint8Array): number {
  let sum = 0;
  for (let i = 0; i < dataArray.length; i++) {
    const v = dataArray[i] ?? 0;
    sum += v * v;
  }
  return Math.sqrt(sum / dataArray.length);
}
