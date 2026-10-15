/**
 * 客户端定转 WAV（ADR-0007-R1 ASR 通道）：MediaRecorder 容器（webm/mp4）
 * 统一转 16kHz 单声道 PCM16 WAV——paraformer 最优输入，消除容器不确定性。
 */

/** AudioBuffer → 16kHz 单声道 Float32（OfflineAudioContext 重采样混单声道）。 */
export async function resampleMono16k(buffer: AudioBuffer): Promise<Float32Array> {
  const targetRate = 16000;
  const length = Math.ceil(buffer.duration * targetRate);
  if (buffer.sampleRate === targetRate && buffer.numberOfChannels === 1) {
    return buffer.getChannelData(0).slice();
  }
  const offline = new OfflineAudioContext(1, length, targetRate);
  const source = offline.createBufferSource();
  source.buffer = buffer;
  source.connect(offline.destination);
  source.start();
  const rendered = await offline.startRendering();
  return rendered.getChannelData(0).slice();
}

/** 单声道采样 → WAV（RIFF/PCM16）字节（ArrayBuffer 便于 Blob 构造）。 */
export function encodeWavPcm16(samples: Float32Array, sampleRate = 16000): ArrayBuffer {
  const bytesPerSample = 2;
  const dataSize = samples.length * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);
  const ascii = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
  };
  ascii(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  ascii(8, "WAVE");
  ascii(12, "fmt ");
  view.setUint32(16, 16, true); // fmt chunk 大小
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // 单声道
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * bytesPerSample, true); // 字节率
  view.setUint16(32, bytesPerSample, true); // 块对齐
  view.setUint16(34, 16, true); // 位深
  ascii(36, "data");
  view.setUint32(40, dataSize, true);
  let offset = 44;
  for (const sample of samples) {
    const clamped = Math.max(-1, Math.min(1, sample));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
    offset += bytesPerSample;
  }
  return buffer;
}

/** 录制 blob → WAV blob（解码 → 重采样 → 编码，一步到位）。 */
export async function blobToWav(blob: Blob): Promise<Blob> {
  const ctx = new AudioContext();
  try {
    const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
    const samples = await resampleMono16k(decoded);
    return new Blob([encodeWavPcm16(samples)], { type: "audio/wav" });
  } finally {
    void ctx.close();
  }
}
