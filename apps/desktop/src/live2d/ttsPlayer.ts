/**
 * ttsPlayer —— Web Audio 播放 + 实时音量提取（M1-S2/S3，功能清单 2.7）。
 *
 * 不用 <audio> 元素：autoplay 策略把元素播放限在瞬时激活窗口内，而合成
 * 往返常超出该窗口；AudioContext 经任意用户点击 unlock 后常驻 running，
 * BufferSource 可任意时刻调度。AnalyserNode 顺带提供 RMS 音量驱动口型。
 */
export class TtsPlayer {
  private ctx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private source: AudioBufferSourceNode | null = null;
  private samples: Float32Array<ArrayBuffer> | null = null;
  /** 自然播完回调（stop() 主动停不触发）。 */
  onEnded: (() => void) | null = null;

  /** 用户手势时调用解锁（App 根节点 pointerdown），幂等。 */
  unlock(): void {
    const ctx = this.ensureCtx();
    if (ctx && ctx.state === "suspended") void ctx.resume().catch(() => {});
  }

  get playing(): boolean {
    return this.source !== null;
  }

  /** 解码并播放；失败（含 ctx 不可用）返回 false，调用方静默降级。 */
  async play(blob: Blob): Promise<boolean> {
    this.stop();
    const ctx = this.ensureCtx();
    if (!ctx) return false;
    try {
      const buffer = await ctx.decodeAudioData(await blob.arrayBuffer());
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      analyser.connect(ctx.destination);
      source.onended = () => {
        if (this.source !== source) return;
        this.source = null;
        this.analyser = null;
        this.onEnded?.();
      };
      this.source = source;
      this.analyser = analyser;
      this.samples = new Float32Array(analyser.fftSize);
      source.start();
      return true;
    } catch {
      this.source = null;
      this.analyser = null;
      return false;
    }
  }

  stop(): void {
    if (this.source) {
      this.source.onended = null;
      try {
        this.source.stop();
      } catch {
        // 已停止则忽略
      }
      this.source = null;
    }
    this.analyser = null;
  }

  /** RMS 音量 0..1（口型驱动用；静音期返回 0）。 */
  level(): number {
    if (!this.analyser || !this.samples) return 0;
    this.analyser.getFloatTimeDomainData(this.samples);
    let sum = 0;
    for (const v of this.samples) sum += v * v;
    const rms = Math.sqrt(sum / this.samples.length);
    return Math.min(1, rms * 4);
  }

  private ensureCtx(): AudioContext | null {
    if (this.ctx) return this.ctx;
    try {
      this.ctx = new AudioContext();
    } catch {
      this.ctx = null;
    }
    return this.ctx;
  }
}

export const ttsPlayer = new TtsPlayer();
