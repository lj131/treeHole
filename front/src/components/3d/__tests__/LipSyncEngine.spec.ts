/**
 * LipSyncEngine 测试 - TDD 实现
 * RED: 先写测试，观看失败
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { lipSyncEngine } from '../LipSyncEngine';

describe('LipSyncEngine - TDD RED', () => {
  let mockCreateMediaElementSource: any;

  beforeEach(() => {
    // Mock AudioContext
    const mockAnalyser = {
      fftSize: 256,
      smoothingTimeConstant: 0.3,
      frequencyBinCount: 128,
      getByteFrequencyData: vi.fn(),
    };

    mockCreateMediaElementSource = vi.fn(() => ({
      connect: vi.fn(),
    }));

    const mockAudioContext = {
      resume: vi.fn(() => Promise.resolve()),
      close: vi.fn(() => Promise.resolve()),
      createAnalyser: vi.fn(() => mockAnalyser),
      createMediaElementSource: mockCreateMediaElementSource,
    };

    // @ts-ignore
    global.AudioContext = vi.fn().mockImplementation(() => mockAudioContext);
  });

  afterEach(() => {
    lipSyncEngine.dispose();
  });

  it('第一个测试：RMS 计算静音应为 0', () => {
    // 这个测试应该失败，因为我们还没有实现可测试的接口
    // 预期：静音数据（全 0）的 RMS 为 0

    // 先让测试能够运行，然后观看它失败
    const silentData = new Uint8Array(128).fill(0);
    const rms = calculateTestRMS(silentData);

    expect(rms).toBe(0);
  });

  it('第二个测试：startElementAnalysis 调用 createMediaElementSource', () => {
    const audioEl = document.createElement('audio');

    lipSyncEngine.startElementAnalysis(audioEl, vi.fn());

    expect(mockCreateMediaElementSource).toHaveBeenCalledWith(audioEl);
  });

  it('第三个测试：stop(true) 发送强度 0', () => {
    const audioEl = document.createElement('audio');
    const callback = vi.fn();

    lipSyncEngine.startElementAnalysis(audioEl, callback);
    lipSyncEngine.stop(true);

    expect(callback).toHaveBeenCalledWith(0);
  });
});

// 测试辅助函数（临时，用于验证测试逻辑）
function calculateTestRMS(dataArray: Uint8Array): number {
  let sum = 0;
  for (let i = 0; i < dataArray.length; i++) {
    const v = dataArray[i] ?? 0;
    sum += v * v;
  }
  return Math.sqrt(sum / dataArray.length);
}