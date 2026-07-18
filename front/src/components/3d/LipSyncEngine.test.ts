/**
 * LipSyncEngine 测试
 * TDD: 先写测试，观看失败，再实现最小代码
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { LipSyncEngine } from './LipSyncEngine';

describe('LipSyncEngine', () => {
  let engine: LipSyncEngine;
  let mockAudioContext: any;

  beforeEach(() => {
    engine = new LipSyncEngine();

    // Mock AudioContext
    mockAudioContext = {
      resume: vi.fn(() => Promise.resolve()),
      close: vi.fn(() => Promise.resolve()),
      createAnalyser: vi.fn(() => ({
        fftSize: 256,
        smoothingTimeConstant: 0.3,
        frequencyBinCount: 128,
        getByteFrequencyData: vi.fn(),
      })),
      createMediaElementSource: vi.fn(() => ({
        connect: vi.fn(),
      })),
    };

    // @ts-ignore - 覆盖全局 AudioContext
    global.AudioContext = vi.fn(() => mockAudioContext);
  });

  afterEach(() => {
    engine.dispose();
  });

  describe('音量计算', () => {
    it('计算静音时返回 0', () => {
      // 预期：当音频数据全为 0 时，计算结果应为 0
      // 需要先实现 calculateRMS 方法可见性或通过行为测试
      expect(true).toBe(false); // 测试失败
    });

    it('计算最大音量时返回接近最大值', () => {
      // 预期：当音频数据全为 255 时，计算结果应接近最大值
      expect(true).toBe(false); // 测试失败
    });
  });

  describe('强度映射', () => {
    it('静音音量映射为 0 强度', () => {
      // 预期：音量低于阈值时强度为 0
      expect(true).toBe(false); // 测试失败
    });

    it('中等音量映射为中间强度', () => {
      // 预期：音量在阈值和最大值之间时线性映射
      expect(true).toBe(false); // 测试失败
    });

    it('最大音量映射为 1 强度', () => {
      // 预期：音量达到最大值时强度为 1
      expect(true).toBe(false); // 测试失败
    });
  });

  describe('音频元素分析', () => {
    it('首次调用创建 MediaElementSource', () => {
      const audioEl = document.createElement('audio');
      const mockCallback = vi.fn();

      engine.startElementAnalysis(audioEl, mockCallback);

      // 预期：调用 createMediaElementSource
      expect(mockAudioContext.createMediaElementSource).toHaveBeenCalledWith(audioEl);
      expect(true).toBe(false); // 测试失败
    });

    it('重复调用同一元素复用 MediaElementSource', () => {
      const audioEl = document.createElement('audio');
      const mockCallback = vi.fn();

      engine.startElementAnalysis(audioEl, mockCallback);
      engine.startElementAnalysis(audioEl, mockCallback);

      // 预期：createMediaElementSource 只调用一次
      expect(mockAudioContext.createMediaElementSource).toHaveBeenCalledTimes(1);
      expect(true).toBe(false); // 测试失败
    });
  });

  describe('停止分析', () => {
    it('停止时发送强度 0', () => {
      const audioEl = document.createElement('audio');
      const mockCallback = vi.fn();

      engine.startElementAnalysis(audioEl, mockCallback);
      engine.stop(true);

      // 预期：回调被调用且强度为 0
      expect(mockCallback).toHaveBeenCalledWith(0);
      expect(true).toBe(false); // 测试失败
    });

    it('stop(false) 时不发送强度 0', () => {
      const audioEl = document.createElement('audio');
      const mockCallback = vi.fn();

      engine.startElementAnalysis(audioEl, mockCallback);
      engine.stop(false);

      // 预期：回调没有被调用
      expect(mockCallback).not.toHaveBeenCalledWith(0);
      expect(true).toBe(false); // 测试失败
    });
  });
});