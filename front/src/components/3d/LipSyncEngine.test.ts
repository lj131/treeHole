/**
 * LipSyncEngine 测试
 * TDD: 先写测试，观看失败，再实现最小代码
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { LipSyncEngine } from './LipSyncEngine';

describe('LipSyncEngine', () => {
  let engine: LipSyncEngine;
  let mockAudioContextInstance: any;
  let originalAudioContext: any;

  beforeEach(() => {
    // 保存原始 AudioContext
    // @ts-ignore
    originalAudioContext = globalThis.AudioContext;

    // Mock AudioContext 实例
    mockAudioContextInstance = {
      resume: vi.fn(() => Promise.resolve()),
      close: vi.fn(() => Promise.resolve()),
      createAnalyser: vi.fn(() => ({
        fftSize: 256,
        smoothingTimeConstant: 0.3,
        frequencyBinCount: 128,
        getByteFrequencyData: vi.fn(),
        connect: vi.fn(),
        disconnect: vi.fn(),
      })),
      createMediaElementSource: vi.fn(() => ({
        connect: vi.fn(),
        disconnect: vi.fn(),
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

    // @ts-ignore - 覆盖全局 AudioContext
    globalThis.AudioContext = MockAudioContext;

    // 在 mock 设置之后创建 engine
    engine = new LipSyncEngine();
  });

  afterEach(() => {
    engine.dispose();
    // 恢复原始 AudioContext
    // @ts-ignore
    globalThis.AudioContext = originalAudioContext;
  });

  describe('音频元素分析', () => {
    it('首次调用创建 MediaElementSource', () => {
      const audioEl = document.createElement('audio');
      const mockCallback = vi.fn();

      engine.startElementAnalysis(audioEl, mockCallback);

      expect(mockAudioContextInstance.createMediaElementSource).toHaveBeenCalledWith(audioEl);
    });

    it('重复调用同一元素复用 MediaElementSource', () => {
      const audioEl = document.createElement('audio');
      const mockCallback = vi.fn();

      engine.startElementAnalysis(audioEl, mockCallback);
      engine.startElementAnalysis(audioEl, mockCallback);

      expect(mockAudioContextInstance.createMediaElementSource).toHaveBeenCalledTimes(1);
    });
  });

  describe('停止分析', () => {
    it('停止时发送强度 0', () => {
      const audioEl = document.createElement('audio');
      const mockCallback = vi.fn();

      engine.startElementAnalysis(audioEl, mockCallback);
      engine.stop(true);

      expect(mockCallback).toHaveBeenCalledWith(0);
    });
  });
});