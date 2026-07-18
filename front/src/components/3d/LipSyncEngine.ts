/**
 * Lip Sync Engine - 基于 Web Audio 的轻量唇形同步
 * 使用 RMS（均方根）音量分析控制 MorphTarget
 *
 * 注意：同一 HTMLAudioElement 只能 createMediaElementSource 一次，
 * 因此对已接通过的元素做缓存复用。
 */
export class LipSyncEngine {
  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private source: AudioNode | null = null;
  private isAnalyzing = false;
  private animationFrameId: number | null = null;
  private wiredElements = new WeakMap<HTMLAudioElement, MediaElementAudioSourceNode>();

  private onMorphUpdate?: (intensity: number) => void;

  private initAudioContext() {
    if (!this.audioContext) {
      this.audioContext = new AudioContext({
        latencyHint: 'interactive',
        sampleRate: 44100,
      });
    }

    if (!this.analyser) {
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 256;
      this.analyser.smoothingTimeConstant = 0.3;
    }
  }

  /**
   * 开始分析音频流（实时麦克风）
   */
  startStreamAnalysis(stream: MediaStream, callback?: (intensity: number) => void) {
    this.stop(false);
    this.initAudioContext();
    this.onMorphUpdate = callback;

    try {
      void this.audioContext!.resume();
      this.source = this.audioContext!.createMediaStreamSource(stream);
      this.source.connect(this.analyser!);
      this.startAnalysis();
    } catch (error) {
      console.error('[LipSyncEngine] Failed to start stream analysis:', error);
    }
  }

  /**
   * 开始分析 Audio 元素（TTS / 测试 WAV）
   */
  startElementAnalysis(
    audioElement: HTMLAudioElement,
    callback?: (intensity: number) => void
  ) {
    this.stop(false);
    this.initAudioContext();
    this.onMorphUpdate = callback;

    try {
      const ctx = this.audioContext!;
      const analyser = this.analyser!;
      void ctx.resume();

      let mediaSource = this.wiredElements.get(audioElement);
      if (!mediaSource) {
        mediaSource = ctx.createMediaElementSource(audioElement);
        this.wiredElements.set(audioElement, mediaSource);
        // 接到 destination 才能听到声音；嘴型走 analyser 旁路
        mediaSource.connect(analyser);
        analyser.connect(ctx.destination);
      } else {
        // 已接线：只需保证 analyser 仍在链上
        try {
          mediaSource.connect(analyser);
        } catch {
          // 已连接时再次 connect 可能抛错，忽略
        }
      }

      this.source = mediaSource;
      this.startAnalysis();
    } catch (error) {
      console.error('[LipSyncEngine] Failed to start element analysis:', error);
    }
  }

  private startAnalysis() {
    if (this.isAnalyzing) return;

    this.isAnalyzing = true;
    const dataArray = new Uint8Array(this.analyser!.frequencyBinCount);

    const analyze = () => {
      if (!this.isAnalyzing) return;

      this.analyser!.getByteFrequencyData(dataArray);
      const volume = this.calculateRMS(dataArray);
      const intensity = this.mapVolumeToIntensity(volume);

      if (this.onMorphUpdate) {
        this.onMorphUpdate(intensity);
      }

      this.animationFrameId = requestAnimationFrame(analyze);
    };

    analyze();
  }

  private calculateRMS(dataArray: Uint8Array): number {
    let sum = 0;
    for (let i = 0; i < dataArray.length; i++) {
      const v = dataArray[i] ?? 0;
      sum += v * v;
    }
    return Math.sqrt(sum / dataArray.length);
  }

  private mapVolumeToIntensity(volume: number): number {
    const silenceThreshold = 8;
    const maxVolume = 90;

    if (volume < silenceThreshold) {
      return 0;
    }

    return Math.min((volume - silenceThreshold) / (maxVolume - silenceThreshold), 1);
  }

  /**
   * 停止分析。keepGraph=true 时保留 MediaElement 接线（便于再次播放）。
   */
  stop(resetMouth = true) {
    this.isAnalyzing = false;

    if (this.animationFrameId !== null) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = null;
    }

    // MediaElementSource 不 disconnect，避免破坏复用图
    if (this.source && !(this.source instanceof MediaElementAudioSourceNode)) {
      this.source.disconnect();
    }
    this.source = null;

    if (resetMouth && this.onMorphUpdate) {
      this.onMorphUpdate(0);
    }
  }

  dispose() {
    this.stop(true);

    if (this.audioContext) {
      void this.audioContext.close();
      this.audioContext = null;
    }

    this.analyser = null;
    this.onMorphUpdate = undefined;
    this.wiredElements = new WeakMap();
  }
}

export const lipSyncEngine = new LipSyncEngine();