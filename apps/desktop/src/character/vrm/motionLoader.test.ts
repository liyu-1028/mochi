import { afterEach, describe, expect, it, vi } from "vitest";
import { Quaternion } from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { loadMotionTracks, loadVrmaFile, loadVrmaTracks } from "./motionLoader";

/** Small independently authored test fixture; no downloaded animation is needed by tests. */
function fixture(withVrma = true) {
  const time = new Float32Array([0, 7.25]);
  const q = new Quaternion().setFromAxisAngle({ x: 0, y: 0, z: 1 }, 0.5);
  const data = new Float32Array([...time, 0, 0, 0, 1, ...q.toArray()]);
  const json = {
    asset: { version: "2.0" },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [{ name: "arm" }],
    extensions: withVrma
      ? {
          VRMC_vrm_animation: {
            specVersion: "1.0",
            humanoid: { humanBones: { rightUpperArm: { node: 0 } } },
          },
        }
      : {},
    buffers: [{ byteLength: data.byteLength }],
    bufferViews: [
      { buffer: 0, byteOffset: 0, byteLength: 8 },
      { buffer: 0, byteOffset: 8, byteLength: 32 },
    ],
    accessors: [
      { bufferView: 0, componentType: 5126, count: 2, type: "SCALAR", min: [0], max: [7.25] },
      { bufferView: 1, componentType: 5126, count: 2, type: "VEC4" },
    ],
    animations: [
      {
        samplers: [{ input: 0, output: 1 }],
        channels: [{ sampler: 0, target: { node: 0, path: "rotation" } }],
      },
    ],
  };
  const raw = new TextEncoder().encode(JSON.stringify(json));
  const length = Math.ceil(raw.length / 4) * 4;
  const bytes = new ArrayBuffer(28 + length + data.byteLength);
  const out = new Uint8Array(bytes);
  out.fill(32, 20, 20 + length);
  out.set(raw, 20);
  const view = new DataView(bytes);
  view.setUint32(0, 0x46546c67, true);
  view.setUint32(4, 2, true);
  view.setUint32(8, bytes.byteLength, true);
  view.setUint32(12, length, true);
  view.setUint32(16, 0x4e4f534a, true);
  view.setUint32(20 + length, data.byteLength, true);
  view.setUint32(24 + length, 0x004e4942, true);
  out.set(new Uint8Array(data.buffer), 28 + length);
  return bytes;
}
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("downloaded VRMA import", () => {
  it("reads real clip duration and leaves its authored rotations intact", async () => {
    const gltf = await new GLTFLoader().parseAsync(fixture(), "");
    vi.spyOn(GLTFLoader.prototype, "loadAsync").mockResolvedValue(gltf);
    const tracks = await loadVrmaTracks("download.vrma");
    expect(tracks.duration).toBe(7.25);
    const arm = tracks.rotation.get("rightUpperArm")!;
    expect([...arm.times]).toEqual([0, 7.25]);
    expect(
      new Quaternion().fromArray(arm.values, 4).normalize().angleTo(new Quaternion()),
    ).toBeCloseTo(0.5);
  });
  it("rejects a renamed GLB without the VRMA humanoid extension", async () => {
    const gltf = await new GLTFLoader().parseAsync(fixture(false), "");
    vi.spyOn(GLTFLoader.prototype, "loadAsync").mockResolvedValue(gltf);
    await expect(loadVrmaTracks("fake.vrma")).rejects.toThrow("VRMC_vrm_animation");
    await expect(loadMotionTracks("samba.fbx")).rejects.toThrow("仅支持 .vrma");
    await expect(loadMotionTracks("animation.glb")).rejects.toThrow("仅支持 .vrma");
  });
  it("validates an import and releases its temporary URL on success and failure", async () => {
    const gltf = await new GLTFLoader().parseAsync(fixture(), "");
    const loader = vi.spyOn(GLTFLoader.prototype, "loadAsync").mockResolvedValue(gltf);
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:import");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const file = { name: "Downloaded.VRMA" } as File;
    expect((await loadVrmaFile(file)).duration).toBe(7.25);
    expect(loader).toHaveBeenCalledWith("blob:import");
    loader.mockRejectedValueOnce(new Error("bad data"));
    await expect(loadVrmaFile(file)).rejects.toThrow("bad data");
    expect(create).toHaveBeenCalledTimes(2);
    expect(revoke).toHaveBeenCalledTimes(2);
  });
});
